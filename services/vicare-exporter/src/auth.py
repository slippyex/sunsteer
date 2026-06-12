"""PyViCare auth: OAuth2-PKCE from username+password+client_id, token cached on the PVC.
Targets the heat-pump device (model contains 'vitocal'); the installation also returns the
gateway + room-control devices, which expose few/irrelevant features."""
import os

from PyViCare.PyViCare import PyViCare


def connect_device(token_file):
    # The ~3-4 discovery calls here (installations/gateways/devices + per-device features)
    # are intentionally NOT counted against RateBudget: they run once per pod start, and
    # Recreate + a stable deployment make restarts rare.
    vicare = PyViCare()
    vicare.initWithCredentials(
        os.environ["VICARE_USER"], os.environ["VICARE_PASS"],
        os.environ["VICARE_CLIENT_ID"], token_file)
    if not vicare.devices:
        raise RuntimeError("ViCare returned no devices")
    vitocal = next((d for d in vicare.devices if "vitocal" in d.getModel().lower()), None)
    return vitocal or vicare.devices[0]
