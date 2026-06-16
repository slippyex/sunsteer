"""One batched feature fetch per poll = exactly one API call."""


def poll(device):
    """Returns the raw fetch_all_features() dict. Raises on network/API error (caller guards)."""
    return device.service.fetch_all_features()
