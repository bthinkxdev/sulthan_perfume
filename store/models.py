from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.auth.hashers import make_password
from django.core.validators import EmailValidator
import uuid
import secrets
from datetime import timedelta


class Category(models.Model):
    """Product category model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Categories'
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'display_order']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    @property
    def active_products_count(self):
        """Return count of active products in this category"""
        return self.products.filter(is_active=True).count()


class Product(models.Model):
    ORIGIN_CHOICES = [
        ('france', 'France'),
        ('arabic', 'Arabic'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    
    category = models.ForeignKey(Category, related_name='products', on_delete=models.SET_NULL, 
                                 null=True, blank=True, help_text="Product category")

    short_description = models.CharField(max_length=255)
    full_description = models.TextField()

    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES)
    fragrance_notes = models.CharField(max_length=255)

    price = models.DecimalField(max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(0)])
    image = models.ImageField(upload_to='products/')

    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
            models.Index(fields=['category', 'is_active']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def default_variant(self):
        """Return the first (oldest) variant for display/add-to-cart defaults."""
        return self.variants.order_by('created_at').first()

    @property
    def default_variant_price(self):
        """Gracefully fall back to the legacy product price if no variants exist."""
        default = self.default_variant
        return default.price if default else self.price


class ProductVariant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, related_name='variants', on_delete=models.CASCADE)
    ml = models.PositiveIntegerField(help_text="Size of the variant in ml")
    price = models.DecimalField(max_digits=10, decimal_places=2,
                                validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['product', 'ml'], name='unique_product_ml_variant')
        ]

    def __str__(self):
        return f"{self.product.name} - {self.ml}ml"


class Combo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True)

    image = models.ImageField(upload_to='combos/', null=True, blank=True)

    products = models.ManyToManyField(
        Product,
        related_name='combos',
        through='ComboProduct',
        through_fields=('combo', 'product')
    )
    discount_percentage = models.PositiveIntegerField(
        help_text="Discount percentage (e.g., 10 for 10%)"
    )

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def _generate_unique_slug(self):
        """Create a unique slug from the title, appending a suffix if needed."""
        base_slug = slugify(self.title) or 'combo'
        slug_candidate = base_slug
        counter = 1

        while type(self).objects.filter(slug=slug_candidate).exclude(pk=self.pk).exists():
            slug_candidate = f"{base_slug}-{counter}"
            counter += 1

        return slug_candidate

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def original_price(self):
        """Sum the prices of selected variants in this combo, with a safe fallback."""
        items = self.combo_products.select_related('variant')
        total = Decimal('0.00')
        has_items = False

        for item in items:
            if item.variant:
                total += item.variant.price
                has_items = True

        if not has_items:
            # Fallback for legacy combos without combo_products
            total = sum(
                product.default_variant_price
                for product in self.products.all()
            )

        return total

    def discounted_price(self):
        return self.original_price() * (100 - self.discount_percentage) / 100

    def __str__(self):
        return self.title


class ComboProduct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    combo = models.ForeignKey(
        Combo,
        related_name='combo_products',
        on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        Product,
        related_name='combo_products',
        on_delete=models.CASCADE
    )
    variant = models.ForeignKey(
        ProductVariant,
        related_name='combo_products',
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['combo', 'product'],
                name='unique_product_per_combo'
            )
        ]

    def __str__(self):
        return f"{self.combo.title} - {self.product.name} ({self.variant.ml}ml)"


class Order(models.Model):
    ORDER_STATUS = [
        ('new', 'New'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True, editable=False)
    
    # Link to user if authenticated (optional for backward compatibility)
    user = models.ForeignKey('User', related_name='orders', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Link to cart (for payment tracking)
    cart = models.ForeignKey('Cart', related_name='orders', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Payment fields
    payment_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ])
    payment_reference = models.CharField(max_length=255, blank=True, null=True)
    
    # Razorpay specific fields
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)

    customer_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)

    address_line = models.TextField()
    city = models.CharField(max_length=50)
    district = models.CharField(max_length=50, default='Kasaragod')
    pincode = models.CharField(max_length=10)

    status = models.CharField(max_length=20, choices=ORDER_STATUS, default='new')

    total_amount = models.DecimalField(max_digits=10, decimal_places=2,
                                       validators=[MinValueValidator(0)])

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['status']),
        ]

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"SUL-{timezone.now().strftime('%Y%m%d')}-{str(self.id)[:6]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    ITEM_TYPE = [
        ('product', 'Product'),
        ('combo', 'Combo'),
    ]

    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)

    item_type = models.CharField(max_length=10, choices=ITEM_TYPE)

    product = models.ForeignKey(Product, null=True, blank=True,
                                on_delete=models.SET_NULL)
    combo = models.ForeignKey(Combo, null=True, blank=True,
                              on_delete=models.SET_NULL)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True,
                                on_delete=models.SET_NULL)
    variant_ml = models.PositiveIntegerField(null=True, blank=True)

    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(product__isnull=False) |
                    models.Q(combo__isnull=False)
                ),
                name="orderitem_product_or_combo"
            )
        ]

    def total_price(self):
        return self.price_at_purchase * self.quantity

    def __str__(self):
        return f"{self.item_type} - {self.order.order_number}"


class SiteConfig(models.Model):
    site_name = models.CharField(max_length=100, default="Sulthan Fragrance")
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    instagram_url = models.URLField()
    location = models.CharField(max_length=100, default="Kasaragod")

    class Meta:
        verbose_name = "Site Configuration"

    def __str__(self):
        return self.site_name


# Authentication Models
class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication"""
    def create_user(self, email, name=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        # Set an unusable password since we use OTP
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, name, **extra_fields)


class User(AbstractBaseUser):
    """Custom user model with email as primary identifier"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, validators=[EmailValidator()])
    name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
        ]
    
    def __str__(self):
        return self.email
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser
    
    def has_module_perms(self, app_label):
        return self.is_superuser


class OTP(models.Model):
    """OTP model for email-based authentication"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    otp_hash = models.CharField(max_length=255)  # Hashed OTP
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'is_used']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"OTP for {self.email} - {'Used' if self.is_used else 'Active'}"
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def is_valid(self):
        return not self.is_used and not self.is_expired()
    
    @staticmethod
    def generate_otp():
        """Generate a 4-digit numeric OTP"""
        return f"{secrets.randbelow(10000):04d}"
    
    @staticmethod
    def create_otp(email, ip_address=None):
        """Create a new OTP for the given email"""
        # Invalidate old OTPs for this email
        OTP.objects.filter(email=email, is_used=False).update(is_used=True)
        
        # Generate new OTP
        otp_code = OTP.generate_otp()
        otp_hash = make_password(otp_code)
        
        # Create OTP record
        otp = OTP.objects.create(
            email=email,
            otp_hash=otp_hash,
            expires_at=timezone.now() + timedelta(minutes=10),
            ip_address=ip_address
        )
        
        return otp, otp_code
    
    def verify(self, otp_code):
        """Verify the provided OTP code"""
        from django.contrib.auth.hashers import check_password
        if self.is_valid() and check_password(otp_code, self.otp_hash):
            self.is_used = True
            self.save()
            return True
        return False


class Address(models.Model):
    """User address model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name='addresses', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    address_line = models.TextField()
    city = models.CharField(max_length=50)
    district = models.CharField(max_length=50, default='Kasaragod')
    pincode = models.CharField(max_length=10)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_default', '-created_at']
        verbose_name_plural = 'Addresses'
    
    def __str__(self):
        return f"{self.name} - {self.city}, {self.district}"
    
    def save(self, *args, **kwargs):
        # If this is set as default, unset other defaults for this user
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)


class Cart(models.Model):
    """Shopping cart model - one active cart per user"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('checked_out', 'Checked Out'),
        ('abandoned', 'Abandoned'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name='carts', on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'status']),
        ]
    
    def __str__(self):
        if self.user:
            return f"Cart for {self.user.email} - {self.status}"
        return f"Guest Cart - {self.status}"
    
    def get_total(self):
        """Calculate total cart amount"""
        return sum(item.subtotal for item in self.items.all())
    
    def get_item_count(self):
        """Get total number of items in cart"""
        return sum(item.quantity for item in self.items.all())
    
    def get_or_create_active_cart(user=None):
        """Get or create an active cart for a user"""
        if user and user.is_authenticated:
            cart, created = Cart.objects.get_or_create(
                user=user,
                status='active',
                defaults={}
            )
            return cart, created
        return None, False


class CartItem(models.Model):
    """Cart item model"""
    ITEM_TYPE = [
        ('product', 'Product'),
        ('combo', 'Combo'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    item_type = models.CharField(max_length=10, choices=ITEM_TYPE)
    
    # Product fields
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE)
    variant_ml = models.PositiveIntegerField(null=True, blank=True)
    
    # Combo fields
    combo = models.ForeignKey(Combo, null=True, blank=True, on_delete=models.CASCADE)
    
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(product__isnull=False) |
                    models.Q(combo__isnull=False)
                ),
                name="cartitem_product_or_combo"
            ),
            models.UniqueConstraint(
                fields=['cart', 'item_type', 'product', 'variant'],
                condition=models.Q(item_type='product'),
                name='unique_product_variant_in_cart'
            ),
            models.UniqueConstraint(
                fields=['cart', 'item_type', 'combo'],
                condition=models.Q(item_type='combo'),
                name='unique_combo_in_cart'
            ),
        ]
    
    @property
    def subtotal(self):
        """Calculate subtotal for this item"""
        return self.price_at_time * self.quantity
    
    def __str__(self):
        if self.item_type == 'product':
            return f"{self.product.name} ({self.variant.ml}ml) - Qty: {self.quantity}"
        return f"{self.combo.title} - Qty: {self.quantity}"
