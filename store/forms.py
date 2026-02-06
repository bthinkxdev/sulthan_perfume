from django import forms
from django.forms import inlineformset_factory
from .models import Product, ProductVariant, Combo, ComboProduct, Order, Category


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'category', 'short_description', 'full_description',
            'origin', 'fragrance_notes', 'price', 'image',
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
                'placeholder': 'Optional: e.g., Vanilla, Jasmine, Musk'
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
        # Make origin and fragrance_notes optional
        self.fields['origin'].required = False
        self.fields['fragrance_notes'].required = False


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['quantity_value', 'quantity_unit', 'ml', 'price', 'is_active']
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
            'ml': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '[Legacy] Size in ml (e.g., 50, 100)'
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
        self.fields['ml'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        quantity_value = cleaned_data.get('quantity_value')
        quantity_unit = cleaned_data.get('quantity_unit')
        ml = cleaned_data.get('ml')
        
        # If quantity_value is provided, quantity_unit must also be provided
        if quantity_value and not quantity_unit:
            raise forms.ValidationError("Quantity unit is required when quantity value is provided.")
        
        # If quantity_unit is provided, quantity_value must also be provided
        if quantity_unit and not quantity_value:
            raise forms.ValidationError("Quantity value is required when quantity unit is provided.")
        
        # At least one quantity system should be provided (new or legacy)
        if not quantity_value and not ml:
            raise forms.ValidationError("Either quantity (value + unit) or legacy ml must be provided.")
        
        return cleaned_data


ProductVariantFormSet = inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    fields=['quantity_value', 'quantity_unit', 'ml', 'price', 'is_active'],
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


ComboProductFormSet = inlineformset_factory(
    Combo,
    ComboProduct,
    form=ComboProductForm,
    fields=['product', 'variant'],
    extra=2,
    can_delete=True,
    min_num=1,
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