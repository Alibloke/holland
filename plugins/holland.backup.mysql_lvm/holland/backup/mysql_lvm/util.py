"""Utility functions to help out the mysql-lvm plugin"""
import os
import shutil
import tempfile
import logging
from holland.core.exceptions import BackupError
from holland.core.util.fmt import format_bytes
from holland.lib.mysql import PassiveMySQLClient, MySQLError, \
                              build_mysql_config, connect
from holland.lib.compression import open_stream
from holland.lib.lvm import Snapshot
from holland.backup.mysql_lvm.actions import FlushAndLockMySQLAction, \
                                             RecordMySQLReplicationAction, \
                                             InnodbRecoveryAction, \
                                             TarArchiveAction

LOG = logging.getLogger(__name__)

def connect_simple(config):
    """Create a MySQLClientConnection given a mysql:client config
    section from a holland mysql backupset
    """
    try:
        mysql_config = build_mysql_config(config)
        LOG.debug("mysql_config => %r", mysql_config)
        connection = connect(mysql_config['client'], PassiveMySQLClient)
        connection.connect()
        return connection
    except MySQLError, exc:
        raise BackupError("[%d] %s" % exc.args)

def cleanup_tempdir(path):
    LOG.info("Removing temporary mountpoint %s", path)
    shutil.rmtree(path)

def build_snapshot(config, logical_volume):
    """Create a snapshot process for running through the various steps
    of creating, mounting, unmounting and removing a snapshot
    """
    name = config['snapshot-name'] or \
            logical_volume.lv_name + '_snapshot'
    extent_size = int(logical_volume.vg_extent_size)
    size = config['snapshot-size'] or \
            min(int(logical_volume.vg_free_count), # don't exceed vg_free_count
                (int(logical_volume.lv_size)*0.2) / extent_size,
                (15*1024**3) / extent_size # maximum 15G auto-sized snapshot space
               ) 
    mountpoint = config['snapshot-mountpoint']
    tempdir = False
    if mountpoint is None:
        tempdir = True
        mountpoint = tempfile.mkdtemp()
    snapshot = Snapshot(name, int(size), mountpoint)
    if tempdir:
        snapshot.register('post-unmount', 
                          lambda *args, **kwargs: cleanup_tempdir(mountpoint))
    return snapshot

def setup_actions(snapshot, config, client, snap_datadir, spooldir):
    """Setup actions for a LVM snapshot based on the provided
    configuration.

    Optional actions:
        * MySQL locking
        * InnoDB recovery
        * Recording MySQL replication
    """
    if config['mysql-lvm']['lock-tables']:
        extra_flush = config['mysql-lvm']['extra-flush-tables']
        act = FlushAndLockMySQLAction(client, extra_flush)
        snapshot.register('pre-snapshot', act, priority=100)
        snapshot.register('post-snapshot', act, priority=100)
    if config['mysql-lvm'].get('replication', True):
        repl_cfg = config.setdefault('mysql:replication', {})
        act = RecordMySQLReplicationAction(client, repl_cfg)
        snapshot.register('pre-snapshot', act, 0)
    if config['mysql-lvm']['innodb-recovery']:
        mysqld_config = dict(config['mysqld'])
        mysqld_config['datadir'] = snap_datadir
        if not mysqld_config['tmpdir']:
            mysqld_config['tmpdir'] = tempfile.gettempdir()
        act = InnodbRecoveryAction(mysqld_config)
        snapshot.register('post-mount', act, priority=100)
        errlog_src = os.path.join(snap_datadir, 'innodb_recovery.log')
        errlog_dst = os.path.join(spooldir, 'innodb_recovery.log')
        snapshot.register('pre-unmount',
                          lambda *args, **kwargs: shutil.copyfile(errlog_src, 
                                                                  errlog_dst)
                         )

    archive_stream = open_stream(os.path.join(spooldir, 'backup.tar'),
                                 'w',
                                 **config['compression'])
    act = TarArchiveAction(snap_datadir, archive_stream, config['tar'])
    snapshot.register('post-mount', act, priority=50)

    snapshot.register('pre-remove', log_final_snapshot_size)

def log_final_snapshot_size(event, snapshot):
    """Log the final size of the snapshot before it is removed"""
    snapshot.reload()
    snap_percent = float(snapshot.snap_percent)/100
    snap_size = float(snapshot.lv_size)
    LOG.info("Final LVM snapshot size for %s is %s", 
        snapshot.device_name(), format_bytes(snap_size*snap_percent))
