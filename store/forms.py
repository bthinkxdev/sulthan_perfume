from django import forms
from django.forms import inlineformset_factory
from .models import Product, ProductVariant, Combo, Order


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'short_description', 'full_description',
            'origin', 'fragrance_notes', 'price', 'image',
            'is_featured', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name'
            }),
            'short_description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Brief description (max 255 characters)'
            }),
            'full_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Detailed product description'
            }),
            'origin': forms.Select(attrs={
                'class': 'form-control'
            }),
            'fragrance_notes': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Vanilla, Jasmine, Musk'
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


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['ml', 'price', 'is_active']
        widgets = {
            'ml': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Size in ml (e.g., 50, 100)'
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


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    fields=['ml', 'price', 'is_active'],
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False
)


class ComboForm(forms.ModelForm):
    class Meta:
        model = Combo
        fields = [
            'title', 'image', 'products',
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
            'products': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-check-input'
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['products'].queryset = Product.objects.filter(is_active=True)


class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
        }