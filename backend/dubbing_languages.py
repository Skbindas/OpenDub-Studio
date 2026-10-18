"""Validated target codes shared by synthesis and content checks."""
def target_language(value='hi'):
    value = str(value or 'hi').lower().strip()
    aliases = {'hi': ('hi','Hindi'), 'hindi': ('hi','Hindi'), 'en': ('en','English'), 'english': ('en','English')}
    if value not in aliases:
        raise ValueError('This genuine synthesis path currently supports Hindi and English. Choose a supported target.')
    return aliases[value]
