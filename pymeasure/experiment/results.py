#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2016 Colin Jermain, Graham Rowlands
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import logging
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

from .procedure import Procedure, UnknownProcedure
from .parameters import Parameter

import os
from datetime import datetime
import re
import pandas as pd


def unique_filename(directory, prefix='DATA', suffix='', ext='csv', dated_folder=False):
    """ Returns a unique filename based on the directory and prefix
    """
    now = datetime.now()
    directory = os.path.abspath(directory)
    if dated_folder:
        directory = os.path.join(directory, now.strftime("%Y-%m-%d"))
    if not os.path.exists(directory):
        os.makedirs(directory)
    i = 1
    basename = "%s%s" % (prefix, now.strftime("%Y%m%d"))
    basepath = os.path.join(directory, basename)
    filename = "%s_%d%s.%s" % (basepath, i, suffix, ext)
    while os.path.exists(filename):
        i += 1
        filename = "%s_%d%s.%s" % (basepath, i, suffix, ext)
    return filename


class Results(object):
    """ The Results class provides a convenient interface to reading and
    writing data in connection with a :class:`.Procedure` object.

    :cvar COMMENT: The character used to identify a comment (default: #)
    :cvar DELIMITER: The character used to delimit the data (default: ,)
    :cvar LINE_BREAK: The character used for line breaks (default \\n)
    :cvar CHUNK_SIZE: The length of the data chuck that is read

    :param procedure: Procedure object
    :param data_filename: The data filename where the data is or should be
                          stored
    """

    COMMENT = '#'
    DELIMITER = ','
    LINE_BREAK = "\n"
    CHUNK_SIZE = 1000

    def __init__(self, procedure, data_filename):
        if not isinstance(procedure, Procedure):
            raise ValueError("Results require a Procedure object")
        self.procedure = procedure
        self.procedure_class = procedure.__class__
        self.parameters = procedure.parameter_objects()
        self._header_count = -1

        self.data_filename = data_filename
        if os.path.exists(data_filename):  # Assume header is already written
            self.reload()
            self.procedure.status = Procedure.FINISHED
            # TODO: Correctly store and retrieve status
        else:
            with open(data_filename, 'w') as f:
                f.write(self.header())
                f.write(self.labels())
            self._data = None

    def header(self):
        """ Returns a text header to accompany a datafile so that the procedure
        can be reconstructed
        """
        h = []
        procedure = re.search("'(?P<name>[^']+)'",
                              repr(self.procedure_class)).group("name")
        h.append("Procedure: <%s>" % procedure)
        h.append("Parameters:")
        for name, parameter in self.parameters.items():
            h.append("\t%s: %s" % (parameter.name, str(parameter)))
        h.append("Data:")
        self._header_count = len(h)
        h = [Results.COMMENT + l for l in h]  # Comment each line
        return Results.LINE_BREAK.join(h) + Results.LINE_BREAK

    def labels(self):
        """ Returns the columns labels as a string to be written
        to the file
        """
        return (Results.DELIMITER.join(self.procedure.DATA_COLUMNS) +
                Results.LINE_BREAK)

    def format(self, data):
        """ Returns a formatted string containing the data to be written
        to a file
        """
        rows = [str(data[x]) for x in self.procedure.DATA_COLUMNS]
        return Results.DELIMITER.join(rows) + Results.LINE_BREAK

    def parse(self, line):
        """ Returns a dictionary containing the data from the line """
        data = {}
        items = line.split(Results.DELIMITER)
        for i, key in enumerate(self.procedure.DATA_COLUMNS):
            data[key] = items[i]
        return data

    @staticmethod
    def parse_header(header, procedure_class=None):
        """ Returns a Procedure object with the parameters as defined in the
        header text.
        """
        if procedure_class is not None:
            procedure = procedure_class()
        else:
            procedure = None

        header = header.split(Results.LINE_BREAK)
        procedure_module = None
        parameters = {}
        for line in header:
            if line.startswith(Results.COMMENT):
                line = line[1:]  # Uncomment
            else:
                raise ValueError("Parsing a header which contains "
                                 "uncommented sections")
            if line.startswith("Procedure"):
                regex = "<(?:(?P<module>[^>]+)\.)?(?P<class>[^.>]+)>"
                search = re.search(regex, line)
                procedure_module = search.group("module")
                procedure_class = search.group("class")
            elif line.startswith("\t"):
                regex = ("\t(?P<name>[^:]+):\s(?P<value>[^\s]+)"
                         "(?:\s(?P<units>.+))?")
                search = re.search(regex, line)
                if search is None:
                    raise Exception("Error parsing header line %s." % line)
                else:
                    parameters[search.group("name")] = (
                        search.group("value"),
                        search.group("units")
                    )
        if procedure is None:
            if procedure_class is None:
                raise ValueError("Header does not contain the Procedure class")
            try:
                from importlib import import_module
                module = import_module(procedure_module)
                procedure_class = getattr(module, procedure_class)
                procedure = procedure_class()
            except ImportError:
                procedure = UnknownProcedure(parameters)
                log.warning("Unknown Procedure in %s" % self.data_filename)
            except Exception as e:
                raise e

        def units_found(parameter, units):
            return (hasattr(parameter, 'units') and
                    parameter.units is None and
                    type(parameter) is Parameter and
                    units is not None)

        # Fill the procedure with the parameters found
        for name, parameter in procedure.parameter_objects().items():
            if parameter.name in parameters:
                value, units = parameters[parameter.name]

                if units_found(parameter, units):
                    # Force full string to be matched
                    value = value + " " + str(units)
                setattr(procedure, name, value)
            else:
                raise Exception("Missing '%s' parameter when loading '%s' class" % (
                        parameter.name, procedure_class))
        procedure.refresh_parameters()  # Enforce update of meta data
        return procedure

    @staticmethod
    def load(data_filename, procedure_class=None):
        """ Returns a Results object with the associated Procedure object and
        data
        """
        header = ""
        header_read = False
        header_count = 0
        with open(data_filename, 'r') as f:
            while not header_read:
                line = f.readline()
                if line.startswith(Results.COMMENT):
                    header += line.strip() + Results.LINE_BREAK
                    header_count += 1
                else:
                    header_read = True
        procedure = Results.parse_header(header[:-1], procedure_class)
        results = Results(procedure, data_filename)
        results._header_count = header_count
        return results

    @property
    def data(self):
        # Need to update header count for correct referencing
        if self._header_count == -1:
            self._header_count = len(
                self.header()[-1].split(Results.LINE_BREAK))
        if self._data is None or len(self._data) == 0:
            # Data has not been read
            try:
                self.reload()
            except:
                # Empty dataframe
                self._data = pd.DataFrame(columns=self.procedure.DATA_COLUMNS)
        else:  # Concatenate additional data
            skiprows = len(self._data) + self._header_count
            chunks = pd.read_csv(
                self.data_filename,
                comment=Results.COMMENT,
                header=0,
                names=self._data.columns,
                chunksize=Results.CHUNK_SIZE, skiprows=skiprows, iterator=True
            )
            try:
                tmp_frame = pd.concat(chunks, ignore_index=True)
                self._data = pd.concat([self._data, tmp_frame],
                                       ignore_index=True)
            except:
                pass  # All data is up to date
        return self._data

    def reload(self):
        """ Preforms a full reloading of the file data, neglecting
        any changes in the comments
        """
        chunks = pd.read_csv(
            self.data_filename,
            comment=Results.COMMENT,
            chunksize=Results.CHUNK_SIZE,
            iterator=True
        )
        try:
            self._data = pd.concat(chunks, ignore_index=True)
        except:
            self._data = chunks.read()