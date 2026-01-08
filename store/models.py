from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.utils.text import slugify
from django.utils import timezone
import uuid


class Product(models.Model):
    ORIGIN_CHOICES = [
        ('france', 'France'),
        ('arabic', 'Arabic'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
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

    customer_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)

    address_line = models.TextField()
    city = models.CharField(max_length=50)
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
