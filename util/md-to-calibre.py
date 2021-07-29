#!/usr/bin/env python3
# The above is the correct Python shebang, see https://stackoverflow.com/a/19305076 . 
# Since it determines the python3 executeable from $PATH, it also works with Python's venv.

# Documentation and command line option description string in the DOCOPT format.
# See: http://docopt.org/ and https://github.com/docopt/docopt
__doc__ = """
A script to import a bibliography list in Markdown with specific convention into a Calibre database.
The format conventions for the book list are as seen at https://edgeryders.eu/t/8791

USAGE:
    md-to-calibre.py [-v] BOOKLIST_FILE CALIBREDB_DIR
    md-to-calibre.py -h

OPTIONS:
    -h, --help     Show this usage and options help message.
    -v, --verbose  Verbose mode to aid in debugging.

INSTALLATION:
    1. Create and activate a virtual environment:
        python3 -m venv ./venv
        . ./venv/bin/activate
    2. Install necessary dependencies:
        pip3 install wheel
        pip3 install docopt markdown
    3. Run the script with suitable command-line arguments:
        autarkylib2calibre.py --help
"""

# TO-DO List
# TODO: To speed the process up, use a direct SQLite connection or via an API. Because starting one 
#   process for every database access (as currently with calibredb) is really slow. API candidates: 
#   the official Calibre database API or better the SqlAlchemy based object-relational mapper used 
#   inside Calibre Web.
#   Example:
#   import sqlite3
#   db_connection = sqlite3.connect(args['CALIBREDB'])
#   db_cursor = db_connection.cursor()
#   db_cursor.executemany('INSERT INTO tablename VALUES (?,?,?,…)', booklist_dicts)
#   db_connection.commit()
#   db_connection.close()
# TODO: Fix that Markdown lists are not yet converted to HTML. This might be because they do not 
#   have a blank line above them, which has been corrected in the source files now but not yet 
#   tested during importing. Affects three books: Autarky Library book IDs 28, 29, 244. So far, 
#   the error has been fixed manually in the script output.
# TODO: Fix that empty lines containing just space characters are not yet recognized as separating 
#   literature entries. (Not important, as this has been fixed in the source file to import now.)
# TODO: Allow "[" and "]" inside link text as long as they appear in matched pairs. Not important, 
#   as these characters are no longer used in the current list to import ("Autarky Library").


# Python standard library packages.
import re
import logging
import sys
import subprocess

# Custom PyPi packages.
from docopt import docopt
import markdown


def calibredb_title_args(dict):
    """Catch and log errors related to the title field, and provide the title in a safe format."""
    if dict['title'] is not None:
        return ['--title', dict['title']]
    else:
        log.error(f'No title in book record with ID {dict["id"]}')
        # ['--title', ''] would also work, but ['--title', None] would crash the subprocess.run 
        # call to calibredb later.
        return []


def calibredb_pubdate_args(dict):
    """Render a publication date in the yyyy-mm-dd format expected by calibredb."""
    if dict['year'] is not None:
        return ['--field', f'pubdate:{dict["year"]}-01-01']
    else:
        # Returning an empty list so that no "--field pubdate:…" will be included in the 
        # calibredb call at all, keeping the value "Undefined", which is internally represented as 
        # 0101-01-01T01:00:00+01:00. A literal of "" would have the same effect.
        return []


def calibredb_pages_args(dict):
    """Render a page count in the format expected by calibredb."""
    if dict['pages'] is not None:
        return ['--field', f'#pages:{dict["pages"]}']
    else:
        return []


def calibredb_link_args(dict):
    """Render the Calibre link field name and value appropriate for the link we have."""
    if dict['link'] is None:
        return []
    elif dict['link'].endswith('.pdf'):
        return ['--field', f'#link_pdf:{dict["link"]}']
    elif dict['link'].endswith('.epub'):
        return ['--field', f'#link_epub:{dict["link"]}']
    else:
        return ['--field', f'#link_meta:{dict["link"]}']


def calibredb_comments_args(dict):
    """Provide calibredb arguments to render additional metadata into the comments field."""
    if dict['description'] is not None:
        description_html = markdown.markdown(dict['description'])
        return ['--field', f'comments:<div>{description_html}</div>']
    else:
        return []


#################### MAIN SCRIPT START ####################

# Configure logging to stdout. See: https://stackoverflow.com/a/28194953
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger(__name__)

args = docopt(__doc__)

#### (1) Read the input file into a list of lines.
with open(args['BOOKLIST_FILE'], 'r') as booklist_file: booklist_lines = booklist_file.readlines()

#### (2)  Convert the list of lines into a list of book entries that we can parse later.
last_line_empty = False
booklist_entries = []
entry = ''
for line in booklist_lines:
    entry_number_match = re.search(r"(^[1-9]+[0-9]*)\. ", line)

    if last_line_empty and entry_number_match:
        if args['--verbose']: log.info("Found booklist entry: %s", entry)
        booklist_entries.append(entry)

        entry = line # Start aggregating the next entry.
    else:
        entry += line

    last_line_empty = (line == "\n")
# Add last entry in the file.
if args['--verbose']: log.info("Found booklist final entry: %s", entry)
booklist_entries.append(entry)

log.info("Booklist entries found: %s", len(booklist_entries))

#### (3) Parse the book list entries one by one and extract the information into a list of dicts.
booklist_dicts = []
entry_regex = re.compile(r'''
    (?P<id>^[1-9]+[0-9]*)\.                     # book id like in "123. "
    \s*
    (?:
        (?: \*\*\[(?P<title1>[^\]]*)\]\((?P<link>.+)\).\*\* ) |  # Title with link.
        (?: \*\*(?P<title2>[^*]*).\*\* )                         # Title without link, rarely used.
    )
    \s*
    (?: (?P<year>[0-9]{4,4})\.)?                 # Optional publishing year.
    \s*
    (?: (?P<pages>[0-9]+)\s+pages\.)?            # Optional page count.
    \s*
    (?s:                                         # ?s to make "." match even \n in tje description.
        (?P<description>.*[^\n])                 # Description. W/o potential final \n.
    )?                                           # Description is optional.
    ''',
    re.VERBOSE # Enable readable regexe as seen above; see https://stackoverflow.com/q/8006551
)
for entry in booklist_entries:
    match = entry_regex.search(entry)

    if not match:
        log.info("Booklist entry could not be parsed: %s", entry)
        continue
    
    dict = match.groupdict()

    # Normalize the dict, cleaning up the title1/2 mess left over from regex processing.
    dict['title'] = dict['title1'] if dict['title1'] is not None else dict['title2']
    dict.pop('title1', None)
    dict.pop('title2', None)

    if args['--verbose']:
        log.info("Creating booklist dict: %s", dict)

    booklist_dicts.append(dict)
    # See: https://docs.python.org/3/library/re.html#re.Match.groupdict

log.info("Booklist dicts created: %s", len(booklist_dicts))

#### (4) Add the book records to the Calibre database.
for dict in booklist_dicts:
    log.info("Import book record with ID %s", dict['id'])

    # Add the main book record to Calibre.
    # Docs: https://docs.python.org/3/library/subprocess.html#using-the-subprocess-module
    run_result = subprocess.run(
        [
            'calibredb', 
            '--library-path', args['CALIBREDB_DIR'],
            'add',
            '--empty',
            *calibredb_title_args(dict),
            # Not setting the author would default to "Unknown", but we want "Unknown Author".
            '--authors', 'Unknown Author'
        ], 
        capture_output = True,
        text = True # Converts captured output to string rather than returning "bytes-like object".
    )
    dict['calibre_id'] = re.findall(r'Added book ids:\s+([0-9]+)', run_result.stdout)[0]
    log.info("Book added to Calibre. calibre_id = %s", dict['calibre_id'])

    # Add additional metadata about the book to Calibre.
    run_result = subprocess.run(
        [
            'calibredb',
            '--library-path', args['CALIBREDB_DIR'],
            'set_metadata',
            *calibredb_pubdate_args(dict),
            *calibredb_pages_args(dict),
            *calibredb_link_args(dict),
            *calibredb_comments_args(dict),
            dict['calibre_id']
        ]
    )
