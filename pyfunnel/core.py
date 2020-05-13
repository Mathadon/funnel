#!/usr/bin/env python
# -*- coding: utf-8 -*-

#######################################################
# Core functions for funnel Python binding
#######################################################

from __future__ import absolute_import, division, print_function, unicode_literals

# Python standard library imports.
from ctypes import cdll, POINTER, c_double, c_int, c_char_p
import io
import numbers
import os
import platform
import re
import subprocess
import sys
import threading
import time
import webbrowser
try:
    from http.server import HTTPServer, SimpleHTTPRequestHandler # Python 3
except ImportError:
    from SimpleHTTPServer import BaseHTTPServer
    HTTPServer = BaseHTTPServer.HTTPServer
    from SimpleHTTPServer import SimpleHTTPRequestHandler # Python 2
# Third-party module or package imports.
import six
# Code repository sub-package imports.


__all__ = ['compareAndReport', 'MyHTTPServer', 'CORSRequestHandler', 'plot_funnel']


#########################################
# Configuration functions and variables #
#########################################

CONFIG_PATH = os.path.join(os.environ.get('HOME'), '.pyfunnel')
CONFIG_DEFAULT = dict(
    BROWSER=None,
)
try:  # Get the real browser name in case webbrowser.get(browser).name returns 'xdg-open' on Ubuntu.
    LINUX_DEFAULT = str(subprocess.check_output('xdg-settings get default-web-browser', shell=True))
except:
    LINUX_DEFAULT = None


def read_config(config_path=CONFIG_PATH, config_default=CONFIG_DEFAULT):
    """Read configuration file and return default values for variables not assigned."""
    try:
        with open(config_path, 'r') as f:
            cfg = f.readlines()
    except FileNotFoundError:
        return config_default
    toreturn = dict()
    for e in cfg:
        (k, v) = re.split('\s*=\s*', e)
        toreturn[k] = v
    for k in config_default.keys():
        if k not in toreturn.keys():
            toreturn[k] = config_default[k]
    return toreturn


CONFIG = read_config()


def save_config(config_path=CONFIG_PATH, config=CONFIG):
    """Save configuration variables in configuration file."""
    with open(config_path, 'w') as f:
        for k in config.keys():
            f.write('{}={}'.format(k, config[k]))


##################
# Free functions #
##################


def follow(filehandler, timeout):
    """Generator yielding lines appended to filehandler until timeout is over."""
    filehandler.seek(0, 2)  # Go to the end of the file.
    must_end = time.time() + timeout
    while time.time() < must_end:
        line = filehandler.readline()
        if not line:  # If no new line: iterate.
            time.sleep(0.1)
            continue
        yield line  # Else: yield line.


def wait_until(somepredicate, timeout, period=0.1, *args, **kwargs):
    """Waits until some predicate is true or timeout is over."""
    must_end = time.time() + timeout
    while time.time() < must_end:
        if somepredicate(*args, **kwargs):
            return True
        time.sleep(period)
    return False


def exit_test(logger, list_files=None):
    """Test if listed files have been loaded by server.

    Based on log of HTTP response status codes:
        200: request received
        304: requested resource not modified since previous transmission
    """
    content = logger.getvalue().decode('utf8')
    if list_files is not None:
        raw_pattern = 'GET.*?{}.*?(200|304)'  # *? for non-greedy search
        for i, l in enumerate(list_files):
            if i == 0:
                pattern = raw_pattern.format(l)
            else:
                pattern = '{}(.*\n)*.*{}'.format(pattern, raw_pattern.format(l))
        return bool(re.search(pattern, content))
    else:
        return False


def plot_funnel(test_dir, title="", browser=None):
    """Plot funnel results stored in test_dir and display in default browser.

    Args:
        test_dir (str): path of directory where output files are stored
        [title] (str): plot title
        [browser] (str): web browser to use for displaying plot
    """
    list_files = ['reference.csv', 'test.csv', 'errors.csv', 'lowerBound.csv', 'upperBound.csv']
    for f in list_files:
        file_path = os.path.join(test_dir, f)
        assert os.path.isfile(file_path), "No such file: {}".format(file_path)

    with open(os.path.join(os.path.dirname(__file__), 'templates', 'plot.html')) as f:
        _TEMPLATE_HTML = f.read()

    content = re.sub('\$TITLE', title, _TEMPLATE_HTML)
    server = MyHTTPServer(('', 0), CORSRequestHandler,
        str_html=content, url_html='funnel', browse_dir=test_dir)
    server.browse(list_files, browser=browser)


def _get_lib_path(project_name):
    """Infer the library absolute path.

    Args:
        project_name (str): project name

    Returns:
        str: guessed library path e.g. ~/project_name/lib/darwin64/lib{project_name}.so
    """
    lib_path = os.path.join(os.path.dirname(__file__), 'lib')
    os_name = platform.system()
    os_machine = platform.machine()
    if os_name == 'Windows':
        if os_machine.endswith('64'):
            lib_path = os.path.join(lib_path, 'win64', '{}.dll'.format(project_name))
        else:
            lib_path = os.path.join(lib_path, 'win32', '{}.dll'.format(project_name))
    elif os_name == 'Linux':
        if os_machine.endswith('64'):
            lib_path = os.path.join(lib_path, 'linux64', 'lib{}.so'.format(project_name))
        else:
            lib_path = os.path.join(lib_path, 'linux32', 'lib{}.so'.format(project_name))
    elif os_name == 'Darwin':
        lib_path = os.path.join(lib_path, 'darwin64', 'lib{}.dylib'.format(project_name))
    else:
        raise RuntimeError('Could not detect standard (system, architecture).')

    return os.path.abspath(lib_path)


def compareAndReport(
    xReference,
    yReference,
    xTest,
    yTest,
    outputDirectory=None,
    atolx=None,
    atoly=None,
    rtolx=None,
    rtoly=None
):
    """Run funnel binary with list-like objects as x, y reference and test values.

    Output `errors.csv`, `lowerBound.csv`, `upperBound.csv`, `reference.csv`,
    `test.csv` into the output directory (`./results` by default).

    Args:
        xReference (list-like of floats): x reference values
        yReference (list-like of floats): y reference values
        xTest (list-like of floats): x test values
        yTest (list-like of floats): y test values
        outputDirectory (str): path of directory to store output files
        atolx (float): absolute tolerance along x axis
        atoly (float): absolute tolerance along y axis
        rtolx (float): relative tolerance along x axis
        rtoly (float): relative tolerance along y axis

    Returns:
        None

    Note: At least one absolute or relative tolerance parameter must be provided for each axis.
    Relative tolerance is relative to the range of x or y values.

    Full documentation at https://github.com/lbl-srg/funnel.
    """

    # Check arguments.
    ## Logic
    assert (atolx is not None) or (rtolx is not None),\
        "At least one of the two possible tolerance parameters (atol or rtol) must be defined for x values."
    assert (atoly is not None) or (rtoly is not None),\
        "At least one of the two possible tolerance parameters (atol or rtol) must be defined for y values."
    ## Type
    if outputDirectory is None:
        print("Output directory not specified: results are stored in subdirectory `results` by default.")
        outputDirectory = "results"
    assert isinstance(outputDirectory, six.string_types),\
        "Path of output directory is not a string type."
    ## Value
    assert len(xReference) == len(yReference),\
        "xReference and yReference must have the same length."
    assert len(xTest) == len(yTest),\
        "xTest and yTest must have the same length."

    # Convert arrays into lists (to support np.array and pd.Series).
    try:
        xReference = list(xReference)
        yReference = list(yReference)
        xTest = list(xTest)
        yTest = list(yTest)
    except Exception as e:
        raise TypeError("Input data could not be converted into lists: {}".format(e))
    # Test numeric type.
    all_data = xReference + yReference + xTest + yTest
    num_check = [isinstance(x, numbers.Real) for x in all_data]
    if not min(num_check):
        idx = filter(lambda i: not num_check[i], range(len(num_check)))
        raise TypeError("The following input values are not numeric: {}".format(
            [all_data[i] for i in idx]
        ))

    # Convert None tolerance to 0.
    tol = dict()
    args = locals()
    for k in ('atolx', 'atoly', 'rtolx', 'rtoly'):
        if args[k] is None:
            tol[k] = 0.0
        else:
            try:
                tol[k] = float(args[k])
            except:
                raise TypeError("Tolerance {} could not be converted to float.".format(k))
            if tol[k] < 0:
                raise ValueError("Tolerance {} must be positive.".format(k))

    # Configure log file path.
    log_path = os.path.join(outputDirectory, 'c_funnel.log')

    # Encode string arguments (in Python 3 c_char_p takes bytes object).
    outputDirectory = outputDirectory.encode('utf-8')

    # Load library.
    try:
        lib_path = _get_lib_path('funnel')
        lib = cdll.LoadLibrary(lib_path)
    except Exception as e:
        raise RuntimeError("Could not load funnel library with this path: {}. {}".format(lib_path, e))

    # Map arguments.
    lib.compareAndReport.argtypes = [
        POINTER(c_double),
        POINTER(c_double),
        c_int,
        POINTER(c_double),
        POINTER(c_double),
        c_int,
        c_char_p,
        c_double,
        c_double,
        c_double,
        c_double]
    lib.compareAndReport.restype = c_int

    # Run
    try:
        retVal = lib.compareAndReport(
            (c_double * len(xReference))(*xReference),
            (c_double * len(yReference))(*yReference),
            len(xReference),
            (c_double * len(xTest))(*xTest),
            (c_double * len(yTest))(*yTest),
            len(xTest),
            outputDirectory,
            tol['atolx'],
            tol['atoly'],
            tol['rtolx'],
            tol['rtoly'],
        )
    except Exception as e:
        raise RuntimeError("Library call raises exception: {}.".format(e))
    if retVal != 0:
        with open(log_path) as f:
            c_stream = f.read()
        print("*** Warning: funnel binary status code is: {}.\n{}".format(retVal, c_stream))
    os.unlink(log_path)

    return retVal


#####################
# Class definitions #
#####################


class MyHTTPServer(HTTPServer):
    """Add custom server_launch, server_close and browse methods."""

    def __init__(self, *args, **kwargs):
        """kwargs:

            str_html (str): HTML content to serve if URL ends with url_html
            url_html (str): pattern used to serve str_html if URL ends with it
            browse_dir (str): path of directory where to launch the server
        """
        str_html = kwargs.pop('str_html', None)
        url_html = kwargs.pop('url_html', None)
        browse_dir = kwargs.pop('browse_dir', os.getcwd())
        HTTPServer.__init__(self, *args)
        self._STR_HTML = re.sub('\$SERVER_PORT', str(self.server_port), str_html)
        self._URL_HTML = url_html
        self._BROWSE_DIR = browse_dir
        self.logger = io.BytesIO()

    def server_launch(self):
        self.thread = threading.Thread(target=self.serve_forever)
        self.thread.daemon = True  # daemonic thread objects are terminated as soon as the main thread exits
        self.thread.start()

    def server_close(self):
        # Invoke to close logger.
        threadd = threading.Thread(target=self.shutdown)  # makes execution stall on Windows if main thread
        threadd.daemon = True
        threadd.start()
        try:
            self.logger.close()
        except Exception as e:
            print('Could not close logger: {}'.format(e))

    def browse(self, *args, **kwargs):
        """Launch server and web browser.

        kwargs:
            browser (str): name of browser, see https://docs.python.org/3.8/library/webbrowser.html
            timeout (float): maximum time (s) before server shutdown
        """
        global CONFIG
        global LINUX_DEFAULT
        browser = kwargs.pop('browser', None)
        timeout = kwargs.pop('timeout', 10)
        # Manage browser command using configuration file.
        cmd = 'import webbrowser; webbrowser.get().open("http://localhost:{}/funnel")'.format(
            self.server_port
        )
        if browser is None:
            # This assignment cannot be done with browser = kwargs.pop('browser', CONFIG['BROWSER'])
            # as another module can call browse(browser=None).
            browser = CONFIG['BROWSER']
        if browser is not None:
            webbrowser.get(browser)  # Throw exception in case of missing browser.
            cmd = re.sub('get\(\)', 'get("{}")'.format(browser), cmd)  # Pass browser name within quotes.
        webbrowser_cmd = [sys.executable, '-c', cmd]
        # Move to directory with *.csv before launching local server.
        cur_dir = os.getcwd()
        os.chdir(self._BROWSE_DIR)
        try:
            self.server_launch()
            # Launch browser as a subprocess command to avoid web browser error into terminal.
            with open(os.devnull, 'w') as pipe:
                proc = subprocess.Popen(webbrowser_cmd, stdout=pipe, stderr=pipe)
            # Watch syslog for error.
            chrome_error = False
            if platform.system() == 'Linux':
                if (browser is None and 'chrome' in LINUX_DEFAULT) or (
                    browser is not None and 'chrome' in browser):
                    with open('/var/log/syslog') as f:
                        for l in follow(f, 2):
                            if 'ERROR:gles2_cmd_decoder' in l:
                                chrome_error = True
                                break
            if chrome_error:
                proc.terminate()  # Terminating the process does not stop Chrome in background.
                subprocess.check_call(['pkill', 'chrome'])  # This does.
                inp = 'y'
                while True:  # Prompt user to retry.
                    inp = input(('Launching browser yields syslog errors, '
                        'probably because Chrome is used and the display entered screensaver mode.\n'
                        'All related processes have been killed by precaution.\n'
                        'If you have Firefox installed and want to use it persistently, enter Y\n'
                        'Otherwise, do you simply want to retry ([y]/n)? '))
                    if inp not in ['y', 'Y', 'n']:
                        continue
                    else:
                        break
                if inp == 'Y':  # Configure Firefox as default browser.
                    CONFIG['BROWSER'] = 'firefox'  # Current module for future calls to the function.
                    save_config()  # Configuration file for future imports.
                    browser = 'firefox'  # Current function for immediate retry.
                    cmd = re.sub('get\(.*?\)', 'get("{}")'.format(browser), cmd)
                    webbrowser_cmd = [sys.executable, '-c', cmd]
                if inp == 'y' or inp == 'Y':
                    # Re initialize logger so wait_until is effective.
                    self.logger = io.BytesIO()
                    with open(os.devnull, 'w') as pipe:
                        proc = subprocess.Popen(webbrowser_cmd, stdout=pipe, stderr=pipe)
                else:
                    raise KeyboardInterrupt
            if timeout > 10:  # Do not pollute terminal if HTML page is served only for a short time.
                print('Server will run for {} (s) or until KeyboardInterrupt.'.format(timeout))
            wait_status = wait_until(exit_test, timeout, 0.1, self.logger, *args)
        except KeyboardInterrupt:
            print('KeyboardInterrupt')
        except Exception as e:
            print(e)
        finally:
            os.chdir(cur_dir)
            try:  # Objects may not be defined in case of exception.
                self.server_close()
                proc.terminate()
                if not wait_status:
                    print('Communication between browser and server failed: '
                        'check that the browser is not running in private mode.')
            except:
                pass


class CORSRequestHandler(SimpleHTTPRequestHandler):
    """Enable logging message and modify response header."""
    def log_message(self, format, *args):
        try:
            to_send = "{} - - [{}] {}\n".format(
                self.client_address[0],
                self.log_date_time_string(),
                format%args
            )
            self.server.logger.write(to_send.encode('utf8'))
        except ValueError:  # logger closed
            pass
        except Exception as e:
            print(e)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin'.encode('utf8'),
            '*'.encode('utf8'))
        self.send_header('Access-Control-Allow-Methods'.encode('utf8'),
            'GET, POST, OPTIONS'.encode('utf8'))
        self.send_header('Access-Control-Allow-Headers'.encode('utf8'),
            'X-Requested-With'.encode('utf8'))
        SimpleHTTPRequestHandler.end_headers(self)

    def send_head(self):
        if (self.server._URL_HTML is not None) and \
           (self.translate_path(self.path).endswith(self.server._URL_HTML)):
            f = io.BytesIO()
            f.write(self.server._STR_HTML.encode('utf8'))
            length = f.tell()
            f.seek(0)
            self.send_response(200)
            self.send_header("Content-type".encode('utf8'), "text/html".encode('utf8'))
            self.send_header("Content-Length".encode('utf8'), str(length).encode('utf8'))
            self.end_headers()
            return f
        else:
            return SimpleHTTPRequestHandler.send_head(self)


