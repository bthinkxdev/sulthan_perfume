"""
Management command to clean up pending/failed orders older than 24 hours.
This ensures that abandoned payments don't clutter the database.

Usage:
    python manage.py cleanup_pending_orders
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from store.models import Order, Cart
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up pending/failed orders older than 24 hours'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Number of hours after which to clean up pending orders (default: 24)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        hours = options['hours']
        dry_run = options['dry_run']
        
        cutoff_time = timezone.now() - timedelta(hours=hours)
        
        # Find orders that are pending or failed and older than cutoff time
        old_orders = Order.objects.filter(
            payment_status__in=['pending', 'failed'],
            created_at__lt=cutoff_time
        )
        
        count = old_orders.count()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'DRY RUN: Would delete {count} orders older than {hours} hours'
                )
            )
            for order in old_orders[:10]:  # Show first 10
                self.stdout.write(
                    f'  - Order {order.order_number} '
                    f'(Status: {order.payment_status}, '
                    f'Created: {order.created_at})'
                )
            if count > 10:
                self.stdout.write(f'  ... and {count - 10} more')
        else:
            # Mark carts as abandoned instead of deleting them
            cart_ids = old_orders.values_list('cart_id', flat=True)
            Cart.objects.filter(id__in=cart_ids).update(status='abandoned')
            
            # Delete the orders
            deleted_count, _ = old_orders.delete()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully cleaned up {deleted_count} old pending/failed orders'
                )
            )
            logger.info(f'Cleaned up {deleted_count} old pending/failed orders')

