"""Standard Holland Backup API classes"""

import logging
from holland.core.plugin import ConfigurablePlugin

LOG = logging.getLogger(__name__)

class BackupError(Exception):
    """Raised when an error is encountered during a backup

    All BackupErrors should derive from this base class
    """

    def __init__(self, message, chained_exc=None):
        self.message = message
        self.chained_exc = chained_exc

    def __str__(self):
        msg = "%s" % self.message
        if self.chained_exc:
            msg += ": %s" % self.chained_exc
        return msg

class BackupPlugin(ConfigurablePlugin):
    """Interface that Holland Backup Plugins should conform to"""

    def pre(self):
        """Run before starting a backup"""

    def estimate(self):
        """Estimate the size of the backup this plugin would produce"""
        raise NotImplementedError()

    def backup(self):
        """Backup to the specified path"""
        raise NotImplementedError()

    def dryrun(self):
        """Perform a dry-run backup to the specified path"""
        raise NotImplementedError()

    def post(self):
        """Run after a backup"""

    def backup_info(self):
        """Provide information about this backup"""
        raise NotImplementedError()

