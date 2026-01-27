/**
 * Cart API Utility - Handles DB-based cart operations
 */

const CartAPI = {
    // Check if user is authenticated
    isAuthenticated: false,
    
    // Initialize cart API
    init: async function() {
        await this.checkAuth();
        if (this.isAuthenticated) {
            await this.loadCart();
        }
    },
    
    // Check authentication status
    checkAuth: async function() {
        try {
            // Check if user is logged in by trying to get cart
            const response = await fetch('/api/cart/', {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            
            if (response.status === 401 || response.status === 403) {
                this.isAuthenticated = false;
                return false;
            }
            
            if (response.ok) {
                this.isAuthenticated = true;
                return true;
            }
            
            return false;
        } catch (error) {
            console.error('Auth check failed:', error);
            this.isAuthenticated = false;
            return false;
        }
    },
    
    // Load cart from server
    loadCart: async function() {
        if (!this.isAuthenticated) {
            return null;
        }
        
        try {
            const response = await fetch('/api/cart/', {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    this.updateCartCount(data.item_count || 0);
                    return data.cart || [];
                }
            }
            return [];
        } catch (error) {
            console.error('Failed to load cart:', error);
            return [];
        }
    },
    
    // Add item to cart
    addToCart: async function(itemData) {
        // Check authentication first
        if (!this.isAuthenticated) {
            const authenticated = await this.checkAuth();
            if (!authenticated) {
                // Show OTP modal
                const nextUrl = window.location.pathname;
                if (typeof openOTPModal === 'function') {
                    openOTPModal(nextUrl);
                } else {
                    window.location.href = '/cart/';
                }
                return { success: false, requires_login: true };
            }
        }
        
        try {
            const response = await fetch('/api/cart/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify(itemData)
            });
            
            const data = await response.json();
            
            if (response.status === 401) {
                // Not authenticated - show login modal
                if (typeof openOTPModal === 'function') {
                    openOTPModal(window.location.pathname);
                }
                return { success: false, requires_login: true };
            }
            
            if (data.success) {
                this.updateCartCount(data.cart_count || 0);
                return data;
            }
            
            return data;
        } catch (error) {
            console.error('Failed to add to cart:', error);
            return { success: false, error: 'Network error' };
        }
    },
    
    // Update cart item quantity
    updateCartItem: async function(itemId, quantity) {
        if (!this.isAuthenticated) {
            return { success: false, requires_login: true };
        }
        
        try {
            const response = await fetch(`/api/cart/item/${itemId}/update/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ quantity: quantity })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.updateCartCount(data.item_count || 0);
            }
            
            return data;
        } catch (error) {
            console.error('Failed to update cart item:', error);
            return { success: false, error: 'Network error' };
        }
    },
    
    // Remove item from cart
    removeFromCart: async function(itemId) {
        if (!this.isAuthenticated) {
            return { success: false, requires_login: true };
        }
        
        try {
            const response = await fetch(`/api/cart/item/${itemId}/remove/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.updateCartCount(data.item_count || 0);
            }
            
            return data;
        } catch (error) {
            console.error('Failed to remove from cart:', error);
            return { success: false, error: 'Network error' };
        }
    },
    
    // Merge session cart to DB cart
    mergeSessionCart: async function() {
        if (!this.isAuthenticated) {
            return { success: false };
        }
        
        // Get session cart from localStorage/sessionStorage
        const sessionCart = this.getSessionCart();
        
        if (!sessionCart || sessionCart.length === 0) {
            return { success: true, message: 'No items to merge' };
        }
        
        try {
            const response = await fetch('/api/cart/merge/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ session_cart: sessionCart })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Clear session cart after successful merge
                this.clearSessionCart();
                this.updateCartCount(data.cart_count || 0);
            }
            
            return data;
        } catch (error) {
            console.error('Failed to merge cart:', error);
            return { success: false, error: 'Network error' };
        }
    },
    
    // Get session cart (for backward compatibility during migration)
    getSessionCart: function() {
        try {
            const cart = sessionStorage.getItem('cart');
            return cart ? JSON.parse(cart) : [];
        } catch (error) {
            return [];
        }
    },
    
    // Clear session cart
    clearSessionCart: function() {
        sessionStorage.removeItem('cart');
    },
    
    // Update cart count in UI
    updateCartCount: function(count) {
        const cartCountElements = document.querySelectorAll('.cart-count, #cart-count, #cart-count-mobile');
        cartCountElements.forEach(el => {
            if (el) el.textContent = count || 0;
        });
        
        // Dispatch event for other scripts
        window.dispatchEvent(new CustomEvent('cart-updated', { detail: { count: count } }));
    },
    
    // Get CSRF token
    getCSRFToken: function() {
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    },
    
    // Show notification
    showNotification: function(message, type = 'success') {
        const notification = document.createElement('div');
        notification.textContent = message;
        notification.className = `cart-notification cart-notification-${type}`;
        notification.style.cssText = `
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: ${type === 'success' ? 'linear-gradient(135deg, #d4af37, #f4d03f)' : '#ef4444'};
            color: #1a1a1a;
            padding: 16px 24px;
            border-radius: 12px;
            font-weight: 600;
            z-index: 10000;
            animation: slideInUp 0.3s ease-out;
            box-shadow: 0 8px 24px rgba(212, 175, 55, 0.4);
        `;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOutDown 0.3s ease-out';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
};

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => CartAPI.init());
} else {
    CartAPI.init();
}

// Export for use in other scripts
window.CartAPI = CartAPI;

