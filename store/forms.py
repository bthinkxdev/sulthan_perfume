from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import Product, ProductVariant, Combo, ComboProduct, Order, Category


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'category', 'short_description',
            'origin', 'price', 'image',
            'is_featured', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Brief description (max 255 characters)'
            }),
            'origin': forms.Select(attrs={
                'class': 'form-control'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'step': '0.01'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        # Make origin optional
        self.fields['origin'].required = False

    def clean_image(self):
        """
        Validate product image:
        - Hard limit: 7 MB (reject anything larger)
        - UI recommendation: keep under 5 MB
        """
        image = self.cleaned_data.get('image')
        if not image:
            return image

        max_bytes = 7 * 1024 * 1024  # 7 MB hard limit

        # Some storage backends might not provide size/content_type, so guard with getattr
        size = getattr(image, 'size', None)
        content_type = getattr(image, 'content_type', '')

        if size is not None and size > max_bytes:
            raise forms.ValidationError(
                "Image is too large. Maximum allowed size is 7 MB. "
                "Please upload an image under 5 MB for best performance."
            )

        if content_type and not content_type.startswith('image/'):
            raise forms.ValidationError("Only image files are allowed.")

        return image


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['quantity_value', 'quantity_unit', 'price', 'is_active']
        widgets = {
            'quantity_value': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Quantity value (e.g., 50, 100, 1.5)',
                'step': '0.01'
            }),
            'quantity_unit': forms.Select(attrs={
                'class': 'form-control',
                'placeholder': 'Select unit'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'step': '0.01'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make quantity fields optional
        self.fields['quantity_value'].required = False
        self.fields['quantity_unit'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        quantity_value = cleaned_data.get('quantity_value')
        quantity_unit = cleaned_data.get('quantity_unit')
        
        # If quantity_value is provided, quantity_unit must also be provided
        if quantity_value and not quantity_unit:
            raise forms.ValidationError("Quantity unit is required when quantity value is provided.")
        
        # If quantity_unit is provided, quantity_value must also be provided
        if quantity_unit and not quantity_value:
            raise forms.ValidationError("Quantity value is required when quantity unit is provided.")
        
        # Quantity fields are optional - variants can be created without quantity (for products without size variants)
        
        return cleaned_data


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    fields=['quantity_value', 'quantity_unit', 'price', 'is_active'],
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False
)


class ComboForm(forms.ModelForm):
    class Meta:
        model = Combo
        fields = [
            'title', 'image',
            'discount_percentage', 'is_featured', 'is_active'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter combo title'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control'
            }),
            'discount_percentage': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter discount % (e.g., 10 for 10%)',
                'min': '0',
                'max': '100'
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

class ComboProductForm(forms.ModelForm):
    class Meta:
        model = ComboProduct
        fields = ['product', 'variant']
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select combo-product-select'
            }),
            'variant': forms.Select(attrs={
                'class': 'form-select combo-variant-select'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)
        self.fields['variant'].queryset = ProductVariant.objects.filter(is_active=True)

        product_id = None
        if self.is_bound:
            product_id = self.data.get(self.add_prefix('product'))
        elif self.instance and self.instance.product_id:
            product_id = self.instance.product_id

        if product_id:
            self.fields['variant'].queryset = ProductVariant.objects.filter(
                product_id=product_id,
                is_active=True
            )

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        variant = cleaned_data.get('variant')

        if product and variant and variant.product_id != product.id:
            raise forms.ValidationError(
                "Selected variant must belong to the chosen product."
            )

        return cleaned_data


class BaseComboProductFormSet(BaseInlineFormSet):
    """Require at least 2 products in a combo."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        # Count non-deleted forms that have a product selected
        count = 0
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                if form.cleaned_data.get('product'):
                    count += 1
        if count < 2:
            raise forms.ValidationError(
                'A combo must have at least 2 products. Add or select products for at least two items.'
            )


ComboProductFormSet = inlineformset_factory(
    Combo,
    ComboProduct,
    form=ComboProductForm,
    formset=BaseComboProductFormSet,
    fields=['product', 'variant'],
    extra=2,
    can_delete=True,
    min_num=2,
    validate_min=True
)


class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
        }