/**
 * Cart API Utility - Handles DB-based cart operations
 */

const CartAPI = {
    // Guest-based: no login; cart is identified by cookie (guest_id)
    isAuthenticated: true,  // Always "ready" for cart operations
    
    // Request tracking to prevent duplicate requests
    _pendingRequests: new Set(),
    _initialized: false,
    
    // Initialize cart API (guest cart via cookie)
    init: async function() {
        if (this._initialized) {
            return;
        }
        this._initialized = true;
        await this.loadCartCount();
    },
    
    // Load cart count only (lightweight)
    loadCartCount: async function() {
        
        // Check cache first (5 second cache to prevent excessive requests)
        const cached = this._getCachedCount();
        if (cached !== null) {
            this.updateCartCount(cached);
            return cached;
        }
        
        // Prevent duplicate simultaneous requests
        const requestKey = 'loadCartCount';
        if (this._pendingRequests.has(requestKey)) {
            return null;
        }
        
        this._pendingRequests.add(requestKey);
        
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
                    const count = data.item_count || 0;
                    this._cacheCount(count);
                    this.updateCartCount(count);
                    return count;
                }
            }
            return 0;
        } catch (error) {
            console.error('Failed to load cart count:', error);
            return 0;
        } finally {
            this._pendingRequests.delete(requestKey);
        }
    },
    
    // Load full cart from server (guest cart via cookie)
    loadCart: async function() {
        // Prevent duplicate simultaneous requests
        const requestKey = 'loadCart';
        if (this._pendingRequests.has(requestKey)) {
            console.log('Cart load already in progress, skipping duplicate request');
            return null;
        }
        
        this._pendingRequests.add(requestKey);
        
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
                    const count = data.item_count || 0;
                    this._cacheCount(count);
                    this.updateCartCount(count);
                    return data.cart || [];
                }
            }
            return [];
        } catch (error) {
            console.error('Failed to load cart:', error);
            return [];
        } finally {
            this._pendingRequests.delete(requestKey);
        }
    },
    
    // Cache management for cart count
    _cacheCount: function(count) {
        sessionStorage.setItem('cart_count_cache', JSON.stringify({
            count: count,
            timestamp: Date.now()
        }));
    },
    
    _getCachedCount: function() {
        try {
            const cached = sessionStorage.getItem('cart_count_cache');
            if (!cached) return null;
            
            const data = JSON.parse(cached);
            const age = Date.now() - data.timestamp;
            
            // Cache valid for 5 seconds
            if (age < 5000) {
                return data.count;
            }
        } catch (e) {
            // Invalid cache
        }
        return null;
    },
    
    _clearCountCache: function() {
        sessionStorage.removeItem('cart_count_cache');
    },
    
    // Add item to cart (guest cart via cookie)
    addToCart: async function(itemData) {
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
            
            if (data.success) {
                this._clearCountCache();
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
                this._clearCountCache(); // Clear cache after cart change
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
                this._clearCountCache(); // Clear cache after cart change
                this.updateCartCount(data.item_count || 0);
            }
            
            return data;
        } catch (error) {
            console.error('Failed to remove from cart:', error);
            return { success: false, error: 'Network error' };
        }
    },
    
    // Merge session cart to DB cart (e.g. after cookie was set)
    mergeSessionCart: async function() {
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
                this._clearCountCache(); // Clear cache after merge
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
    _lastCartCount: null,
    updateCartCount: function(count) {
        const normalizedCount = count || 0;
        
        // Only update if count has changed to prevent unnecessary events
        if (this._lastCartCount === normalizedCount) {
            return;
        }
        
        this._lastCartCount = normalizedCount;
        
        const cartCountElements = document.querySelectorAll('.cart-count, #cart-count, #cart-count-mobile');
        cartCountElements.forEach(el => {
            if (el) el.textContent = normalizedCount;
        });
        
        // Dispatch event for other scripts (only when count actually changes)
        window.dispatchEvent(new CustomEvent('cart-updated', { detail: { count: normalizedCount } }));
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

