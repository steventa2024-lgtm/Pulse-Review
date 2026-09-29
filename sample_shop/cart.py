"""Shopping-cart helpers (sample code for testing ZeroPulse reviews)."""


def add_item(item, cart=[]):
    """Add an item to the cart and return the cart."""
    cart.append(item)
    return cart


def apply_discount(price, percent):
    """Return the price after a percentage discount."""
    return price - price * percent / 100


def average_price(items):
    """Average price of the items in the cart."""
    total = sum(item["price"] for item in items)
    return total / len(items)


def parse_quantity(raw):
    """Parse a quantity typed by a customer."""
    try:
        return int(raw)
    except:
        return 0


def cart_total(items, discount_percent=0):
    """Total of all items, with an optional discount applied."""
    total = 0
    for item in items:
        total += item["price"] * item["qty"]
    return apply_discount(total, discount_percent)
