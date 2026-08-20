#!/usr/bin/env python3
"""
Daily archival job for brief_days.

Run once a day (see k8s/cronjob.yaml). Two independent passes, per
db/README.md's archival semantics:

  1. Soft-delete: brief_date more than 14 days ago AND still 'active'
     -> status = 'archived'. Archived days stop appearing in /api/briefs
     (the "no longer visible to the end user" requirement) but the rows
     and their items still exist.
  2. Hard-delete: brief_date more than 30 days ago, regardless of current
     status -> row deleted, items cascade with it. Irreversible.

Both passes run every time this script runs — a day that's already
archived is simply a no-op for pass 1 and gets picked up by pass 2 once
it crosses 30 days. Idempotent: running this twice in a row (or twice in
the same day, if the CronJob's schedule ever overlaps) does nothing
extra the second time.
"""
import logging
import os
import sys

import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('archive_briefs')

ARCHIVE_AFTER_DAYS = int(os.environ.get('ARCHIVE_AFTER_DAYS', '14'))
DELETE_AFTER_DAYS = int(os.environ.get('DELETE_AFTER_DAYS', '30'))


def main():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        log.error('DATABASE_URL is not set.')
        sys.exit(1)

    if DELETE_AFTER_DAYS <= ARCHIVE_AFTER_DAYS:
        log.error(
            'DELETE_AFTER_DAYS (%s) must be greater than ARCHIVE_AFTER_DAYS (%s) — '
            'a day should be archived before it is ever eligible for deletion.',
            DELETE_AFTER_DAYS, ARCHIVE_AFTER_DAYS,
        )
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE brief_days
                SET status = 'archived', archived_at = now()
                WHERE status = 'active'
                  AND brief_date < (CURRENT_DATE - %s::int)
                """,
                (ARCHIVE_AFTER_DAYS,),
            )
            archived_count = cur.rowcount

            cur.execute(
                """
                DELETE FROM brief_days
                WHERE brief_date < (CURRENT_DATE - %s::int)
                """,
                (DELETE_AFTER_DAYS,),
            )
            deleted_count = cur.rowcount

        conn.commit()
        # archived_count can include rows that were old enough to be archived
        # AND already past the delete threshold in this same run — those get
        # counted here, then deleted in the very next statement. That's
        # correct (they end up deleted either way), just worth knowing if
        # these two numbers don't look mutually exclusive in the logs.
        log.info('Archived %s brief day(s), hard-deleted %s brief day(s).', archived_count, deleted_count)
    except Exception:
        conn.rollback()
        log.exception('Archive job failed, rolled back.')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
