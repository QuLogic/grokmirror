#-*- coding: utf-8 -*-
# Copyright (C) 2013 by The Linux Foundation and contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os

import grokmirror
import logging

import time
import json
import subprocess
import random
import datetime

from fcntl import lockf, LOCK_EX, LOCK_UN, LOCK_NB

# default basic logger. We override it later.
logger = logging.getLogger(__name__)


def run_git_prune(fullpath, config, manifest):
    prune_ok = True
    if 'prune' not in config.keys() or config['prune'] != 'yes':
        return prune_ok

    # Are any other repos using us in their objects/info/alternates?
    gitdir = '/' + os.path.relpath(fullpath, config['toplevel']).lstrip('/')
    repolist = grokmirror.find_all_alt_repos(gitdir, manifest)

    if len(repolist):
        logger.info('  prune : skipped, is alternate to other repos')
        return prune_ok

    env = {'GIT_DIR': fullpath}
    args = ['/usr/bin/git', 'prune']
    logger.info('  prune : pruning')

    logger.debug('Running: GIT_DIR=%s %s' % (env['GIT_DIR'], ' '.join(args)))

    (output, error) = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env).communicate()

    error = error.decode().strip()

    if error:
        # Put things we recognize as fairly benign into debug
        debug = []
        warn = []
        for line in error.split('\n'):
            ignored = False
            for estring in config['ignore_errors']:
                if line.find(estring) != -1:
                    ignored = True
                    debug.append(line)
                    break
            if not ignored:
                warn.append(line)

        if debug:
            logger.debug('Stderr: %s' % '\n'.join(debug))
        if warn:
            logger.critical('Pruning %s returned critical errors:' % fullpath)
            prune_ok = False
            for entry in warn:
                logger.critical("\t%s" % entry)

    return prune_ok


def run_git_repack(fullpath, config, full_repack=False):
    # Returns false if we hit any errors on the way
    repack_ok = True
    if 'repack' not in config.keys() or config['repack'] != 'yes':
        return repack_ok

    repack_flags = '-A -d -l -q'

    if full_repack and 'full_repack_flags' in config.keys():
        repack_flags = config['full_repack_flags']
        logger.debug('Time to do a full repack of %s' % fullpath)

    elif 'repack_flags' in config.keys():
        repack_flags = config['repack_flags']

    flags = repack_flags.split()

    env = {'GIT_DIR': fullpath}
    args = ['/usr/bin/git', 'repack'] + flags
    logger.info(' repack : repacking with %s' % repack_flags)

    logger.debug('Running: GIT_DIR=%s %s' % (env['GIT_DIR'], ' '.join(args)))

    (output, error) = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env).communicate()

    error = error.decode().strip()

    # With newer versions of git, repack may return warnings that are safe to ignore
    # so use the same strategy to weed out things we aren't interested in seeing
    if error:
        # Put things we recognize as fairly benign into debug
        debug = []
        warn = []
        for line in error.split('\n'):
            ignored = False
            for estring in config['ignore_errors']:
                if line.find(estring) != -1:
                    ignored = True
                    debug.append(line)
                    break
            if not ignored:
                warn.append(line)

        if debug:
            logger.debug('Stderr: %s' % '\n'.join(debug))
        if warn:
            logger.critical('Repacking %s returned critical errors:' % fullpath)
            repack_ok = False
            for entry in warn:
                logger.critical("\t%s" % entry)

    if not repack_ok:
        # No need to repack refs if repo is broken
        return False

    # repacking refs requires a separate command, so run it now
    args = ['/usr/bin/git', 'pack-refs', '--all']
    logger.info(' repack : repacking refs')

    logger.debug('Running: GIT_DIR=%s %s' % (env['GIT_DIR'], ' '.join(args)))

    (output, error) = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env).communicate()

    error = error.decode().strip()

    # pack-refs shouldn't return anything, but use the same ignore_errors block
    # to weed out any future potential benign warnings
    if error:
        # Put things we recognize as fairly benign into debug
        debug = []
        warn = []
        for line in error.split('\n'):
            ignored = False
            for estring in config['ignore_errors']:
                if line.find(estring) != -1:
                    ignored = True
                    debug.append(line)
                    break
            if not ignored:
                warn.append(line)

        if debug:
            logger.debug('Stderr: %s' % '\n'.join(debug))
        if warn:
            logger.critical('Repacking refs %s returned critical errors:' % fullpath)
            repack_ok = False
            for entry in warn:
                logger.critical("\t%s" % entry)

    return repack_ok

def run_git_fsck(fullpath, config, conn_only=False):
    env = {'GIT_DIR': fullpath}
    args = ['/usr/bin/git', 'fsck', '--no-dangling']
    if conn_only:
        args.append('--connectivity-only')
        logger.info('   fsck : running with --connectivity-only')
    else:
        logger.info('   fsck : running full checks')

    logger.debug('Running: GIT_DIR=%s %s' % (env['GIT_DIR'], ' '.join(args)))

    (output, error) = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env).communicate()

    error = error.decode().strip()

    if error:
        # Put things we recognize as fairly benign into debug
        debug = []
        warn = []
        for line in error.split('\n'):
            ignored = False
            for estring in config['ignore_errors']:
                if line.find(estring) != -1:
                    ignored = True
                    debug.append(line)
                    break
            if not ignored:
                warn.append(line)

        if debug:
            logger.debug('Stderr: %s' % '\n'.join(debug))
        if warn:
            logger.critical('%s has critical errors:' % fullpath)
            for entry in warn:
                logger.critical("\t%s" % entry)


def fsck_mirror(name, config, verbose=False, force=False, conn_only=False, repack_all_quick=False, repack_all_full=False):
    global logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if 'log' in config.keys():
        ch = logging.FileHandler(config['log'])
        formatter = logging.Formatter(
            "[%(process)d] %(asctime)s - %(levelname)s - %(message)s")
        ch.setFormatter(formatter)
        loglevel = logging.INFO

        if 'loglevel' in config.keys():
            if config['loglevel'] == 'debug':
                loglevel = logging.DEBUG

        ch.setLevel(loglevel)
        logger.addHandler(ch)

    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)

    if verbose:
        ch.setLevel(logging.INFO)
    else:
        ch.setLevel(logging.CRITICAL)

    logger.addHandler(ch)

    # push it into grokmirror to override the default logger
    grokmirror.logger = logger

    if conn_only or repack_all_quick or repack_all_full:
        force = True

    logger.info('Running grok-fsck for [%s]' % name)

    # Lock the tree to make sure we only run one instance
    logger.debug('Attempting to obtain lock on %s' % config['lock'])
    flockh = open(config['lock'], 'w')
    try:
        lockf(flockh, LOCK_EX | LOCK_NB)
    except IOError:
        logger.info('Could not obtain exclusive lock on %s' % config['lock'])
        logger.info('Assuming another process is running.')
        return 0

    manifest = grokmirror.read_manifest(config['manifest'])

    if os.path.exists(config['statusfile']):
        logger.info('Reading status from %s' % config['statusfile'])
        stfh = open(config['statusfile'], 'rb')
        try:
            # Format of the status file:
            #  {
            #    '/full/path/to/repository': {
            #      'lastcheck': 'YYYY-MM-DD' or 'never',
            #      'nextcheck': 'YYYY-MM-DD',
            #      'lastrepack': 'YYYY-MM-DD',
            #      'fingerprint': 'sha-1',
            #      's_elapsed': seconds,
            #      'quick_repack_count': times,
            #    },
            #    ...
            #  }

            status = json.loads(stfh.read().decode('utf-8'))
        except:
            # Huai le!
            logger.critical('Failed to parse %s' % config['statusfile'])
            lockf(flockh, LOCK_UN)
            flockh.close()
            return 1
    else:
        status = {}

    frequency = int(config['frequency'])

    today = datetime.datetime.today()

    # Go through the manifest and compare with status
    for gitdir in manifest.keys():
        fullpath = os.path.join(config['toplevel'], gitdir.lstrip('/'))
        if fullpath not in status.keys():
            # Newly added repository
            # Randomize next check between now and frequency
            delay = random.randint(0, frequency)
            nextdate = today + datetime.timedelta(days=delay)
            nextcheck = nextdate.strftime('%F')
            status[fullpath] = {
                'lastcheck': 'never',
                'nextcheck': nextcheck,
            }
            logger.info('%s:' % fullpath)
            logger.info('  added : next check on %s' % nextcheck)

    total_checked = 0
    total_elapsed = 0

    # Go through status and queue checks for all the dirs that are due today
    # (unless --force, which is EVERYTHING)
    todayiso = today.strftime('%F')
    for fullpath in list(status):
        logger.info('%s:' % fullpath)
        # Check to make sure it's still in the manifest
        gitdir = fullpath.replace(config['toplevel'], '', 1)
        gitdir = '/' + gitdir.lstrip('/')

        if gitdir not in manifest.keys():
            del status[fullpath]
            logger.info('   gone : no longer in manifest')
            continue

        # If nextcheck is before today, set it to today
        # XXX: If a system comes up after being in downtime for a while, this
        #      may cause pain for them, so perhaps use randomization here?
        nextcheck = datetime.datetime.strptime(status[fullpath]['nextcheck'],
                                               '%Y-%m-%d')

        if force or nextcheck <= today:
            logger.debug('Preparing to check %s' % fullpath)
            # Calculate elapsed seconds
            startt = time.time()

            # Did the fingerprint change since last time we repacked?
            oldfpr = None
            if 'fingerprint' in status[fullpath].keys():
                oldfpr = status[fullpath]['fingerprint']

            fpr = grokmirror.get_repo_fingerprint(config['toplevel'], gitdir, force=True)

            if fpr != oldfpr or repack_all_full:
                full_repack = repack_all_full
                if not 'quick_repack_count' in status[fullpath].keys():
                    status[fullpath]['quick_repack_count'] = 0

                quick_repack_count = status[fullpath]['quick_repack_count']
                if 'full_repack_every' in config.keys():
                    # but did you set 'full_repack_flags' as well?
                    if 'full_repack_flags' not in config.keys():
                        logger.critical('full_repack_every is set, but not full_repack_flags')
                    else:
                        full_repack_every = int(config['full_repack_every'])
                        # is it anything insane?
                        if full_repack_every < 2:
                            full_repack_every = 2
                            logger.warning('full_repack_every is too low, forced to 2')

                        # is it time to trigger full repack?
                        # We -1 because if we want a repack every 10th time, then we need to trigger
                        # when current repack count is 9.
                        if quick_repack_count >= full_repack_every-1:
                            logger.debug('Time to do full repack on %s' % fullpath)
                            full_repack = True
                            quick_repack_count = 0
                            status[fullpath]['lastfullrepack'] = todayiso
                        else:
                            logger.debug('Repack count for %s not yet reached full repack trigger' % fullpath)
                            quick_repack_count += 1

                # Don't run repack if we're running --connectivity without --repack-all-*
                if conn_only and not (repack_all_quick or repack_all_full):
                    repack_ok = True
                    logger.debug('No repacking requested with --connectivity')
                else:
                    repack_ok = run_git_repack(fullpath, config, full_repack)
                    if repack_ok:
                        prune_ok = run_git_prune(fullpath, config, manifest)

                status[fullpath]['lastrepack'] = todayiso
                status[fullpath]['quick_repack_count'] = quick_repack_count

            else:
                repack_ok = True
                logger.info(' repack : skipped, unchanged since last run')

            # We fsck last, after repacking and
            if repack_ok:
                # If you set --repack-all-* and --connectivity, then we run fsck,
                # but if only --repack-all-*, then we don't do fsck
                if (repack_all_quick or repack_all_full) and conn_only:
                    run_git_fsck(fullpath, config, conn_only)
                elif not (repack_all_quick or repack_all_full):
                    run_git_fsck(fullpath, config, conn_only)
                else:
                    logger.debug('Skipping fsck as requested.')
            else:
                logger.warning('Repacking %s was unsuccessful, please run fsck manually!' % gitdir)

            total_checked += 1

            endt = time.time()

            total_elapsed += endt-startt

            status[fullpath]['fingerprint'] = fpr
            status[fullpath]['lastcheck'] = todayiso
            status[fullpath]['s_elapsed'] = int(endt - startt)

            if force:
                # Use randomization for next check, again
                delay = random.randint(1, frequency)
            else:
                delay = frequency

            nextdate = today + datetime.timedelta(days=delay)
            status[fullpath]['nextcheck'] = nextdate.strftime('%F')

            # Write status file after each check, so if the process dies, we won't
            # have to recheck all the repos we've already checked
            logger.debug('Updating status file in %s' % config['statusfile'])
            with open(config['statusfile'], 'wb') as stfh:
                stfh.write(json.dumps(status, indent=2).encode('utf-8'))

    if not total_checked:
        logger.info('No new repos to check.')
    else:
        logger.info('Repos checked: %s' % total_checked)
        logger.info('Total running time: %s s' % int(total_elapsed))
        with open(config['statusfile'], 'wb') as stfh:
            stfh.write(json.dumps(status, indent=2).encode('utf-8'))

    lockf(flockh, LOCK_UN)
    flockh.close()


def parse_args():
    from optparse import OptionParser

    usage = '''usage: %prog -c fsck.conf
    Run a git-fsck check on grokmirror-managed repositories.
    '''

    op = OptionParser(usage=usage, version=grokmirror.VERSION)
    op.add_option('-v', '--verbose', dest='verbose', action='store_true',
                  default=False,
                  help='Be verbose and tell us what you are doing')
    op.add_option('-f', '--force', dest='force',
                  action='store_true', default=False,
                  help='Force immediate run on all repositories.')
    op.add_option('-c', '--config', dest='config',
                  help='Location of fsck.conf')
    op.add_option('--connectivity', dest='conn_only',
                  action='store_true', default=False,
                  help='(Assumes --force): Run git fsck on all repos, but only check connectivity')
    op.add_option('--repack-all-quick', dest='repack_all_quick',
                  action='store_true', default=False,
                  help='(Assumes --force): Do a quick repack of all repos')
    op.add_option('--repack-all-full', dest='repack_all_full',
                  action='store_true', default=False,
                  help='(Assumes --force): Do a full repack of all repos')

    opts, args = op.parse_args()

    if opts.repack_all_quick and opts.repack_all_full:
        op.error('Pick either --repack-all-full or --repack-all-quick')

    if not opts.config:
        op.error('You must provide the path to the config file')

    return opts, args


def grok_fsck(config, verbose=False, force=False, conn_only=False, repack_all_quick=False, repack_all_full=False):
    try:
        from configparser import ConfigParser
    except ImportError:
        from ConfigParser import ConfigParser

    ini = ConfigParser()
    ini.read(config)

    for section in ini.sections():
        config = {}
        for (option, value) in ini.items(section):
            config[option] = value

        if 'ignore_errors' not in config:
            config['ignore_errors'] = [
                'notice: HEAD points to an unborn branch',
                'notice: No default references',
                'contains zero-padded file modes',
                'warning: disabling bitmap writing, as some objects are not being packed',
                'ignoring extra bitmap file'
            ]
        else:
            ignore_errors = []
            for estring in config['ignore_errors'].split('\n'):
                estring = estring.strip()
                if len(estring):
                    ignore_errors.append(estring)
            config['ignore_errors'] = ignore_errors

        fsck_mirror(section, config, verbose, force, conn_only, repack_all_quick, repack_all_full)


def command():
    opts, args = parse_args()

    return grok_fsck(opts.config, opts.verbose, opts.force, opts.conn_only, opts.repack_all_quick, opts.repack_all_full)

if __name__ == '__main__':
    command()
