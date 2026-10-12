"""Errors shared by graph target adapters."""


class DeploymentError(RuntimeError):
    """A target rejected or failed a deployment or read; the message is safe to show to users."""
