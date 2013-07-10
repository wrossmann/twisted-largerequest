import tempfile, time, cgi, mimetools, os
from twisted.web import server
from cgi import parse_header as _parseHeader

class LargeRequest(server.Request):
    # max amount of memory to allow any ~single~ request argument [ie: POSTed file]
    # to take up before being flushed into a temporary file.
    # eg:   50 users uploading 4 large files could use up to [and in excess of]
    #       200 times value specified below.
    # note: this value seems to be taken with a grain of salt, memory usage may spike
    #       FAR above this value in some cases.
    #       eg: set the memory limit to 5 MB, write 2 blocks of 4MB, mem usage will
    #           have spiked to 8MB before the data is rolled to disk after the
    #           second write completes. 
    memorylimit = 1024*1024*25
    # type of tempfile to use. Spooled will be fastest for files/parts smaller than
    # memorylimit defiend above, Named will be fastest for file uploads when you want
    # to do:
    #   request.args['file'][0].delete = False
    #   request.args['file'][0].close()
    #   shutil.move(request.args['file'][0].name, new_location)
    # where tempfile.tempdir is on the same filessystem as new_location
    temp_type = staticmethod(tempfile.NamedTemporaryFile)
    # enable/disable debug logging
    do_log = False
    
    # re-defined only for debug/logging purposes
    def gotLength(self, length):
        if self.do_log:
            print '%f Headers received, Content-Length: %d' % (time.time(), length)
        server.Request.gotLength(self, length)
    
    # re-definition of twisted.web.server.Request.requestrecieved, the only difference
    # is that self.parse_multipart() is used rather than cgi.parse_multipart()
    def requestReceived(self, command, path, version):
        if self.do_log:
            print '%f Request Received' % time.time()
        self.content.seek(0,0)
        self.args = {}
        self.stack = []

        self.method, self.uri = command, path
        self.clientproto = version
        x = self.uri.split(b'?', 1)

        if len(x) == 1:
            self.path = self.uri
        else:
            self.path, argstring = x
            self.args = self.parse_qs(argstring, 1)

        # cache the client and server information, we'll need this later to be
        # serialized and sent with the request so CGIs will work remotely
        self.client = self.channel.transport.getPeer()
        self.host = self.channel.transport.getHost()

        # Argument processing
        args = self.args
        ctype = self.requestHeaders.getRawHeaders(b'content-type')
        if ctype is not None:
            ctype = ctype[0]

        if self.method == b"POST" and ctype:
            mfd = b'multipart/form-data'
            key, pdict = _parseHeader(ctype)
            if key == b'application/x-www-form-urlencoded':
                args.update(self.parse_qs(self.content.read(), 1))
            elif key == mfd:
                try:
                    self.content.seek(0,0)
                    args.update(self.parse_multipart(self.content, pdict))
                    #args.update(cgi.parse_multipart(self.content, pdict))

                except KeyError as e:
                    if e.args[0] == b'content-disposition':
                        # Parse_multipart can't cope with missing
                        # content-dispostion headers in multipart/form-data
                        # parts, so we catch the exception and tell the client
                        # it was a bad request.
                        self.channel.transport.write(
                                b"HTTP/1.1 400 Bad Request\r\n\r\n")
                        self.channel.transport.loseConnection()
                        return
                    raise
            self.content.seek(0, 0)

        self.process()
    
    # re-definition of cgi.parse_multipart that uses a single temporary file to store
    # data rather than storing 2 to 3 copies in various lists.
    def parse_multipart(self, fp, pdict):
        if self.do_log:
            print '%f Parsing Multipart data: ' % time.time()
        rewind = fp.tell() #save cursor
        fp.seek(0,0) #reset cursor
        
        boundary = ""
        if 'boundary' in pdict:
            boundary = pdict['boundary']
        if not cgi.valid_boundary(boundary):
            raise ValueError,  ('Invalid boundary in multipart form: %r'
                                % (boundary,))
    
        nextpart = "--" + boundary
        lastpart = "--" + boundary + "--"
        partdict = {}
        terminator = ""
    
        while terminator != lastpart:
            c_bytes = -1
            if self.temp_type.__name__ == 'SpooledTemporaryFile':
                data = self.temp_type(max_size=self.memorylimit)
            else:
                data = self.temp_type()
            if terminator:
                # At start of next part.  Read headers first.
                headers = mimetools.Message(fp)
                clength = headers.getheader('content-length')
                if clength:
                    try:
                        c_bytes = int(clength)
                    except ValueError:
                        pass
                if c_bytes > 0:
                    data.write(fp.read(bytes))
            # Read lines until end of part.
            while 1:
                line = fp.readline()
                if not line:
                    terminator = lastpart # End outer loop
                    break
                if line[:2] == "--":
                    terminator = line.strip()
                    if terminator in (nextpart, lastpart):
                        break
                data.write(line)
            # Done with part.
            if data.tell() == 0:
                continue
            if bytes < 0:
                # if a Content-Length header was not supplied with the MIME part
                # then the trailing line break must be removed. the var 'line'
                # will still contain the last line written for reference.
                if line[-2:] == "\r\n":
                    data.seek(-2, os.SEEK_END)
                    data.truncate()
                elif line[-1:] == "\n":
                    data.seek(-1, os.SEEK_END)
                    data.truncate()

            line = headers['content-disposition']
            if not line:
                continue
            key, params = cgi.parse_header(line)
            if key != 'form-data':
                continue
            if 'name' in params:
                name = params['name']
                # kludge in the filename
                if 'filename' in params:
                    fname_index = name + '_filename'
                    if fname_index in partdict:
                        partdict[fname_index].append(params['filename'])
                    else:
                        partdict[name + '_filename'] = [params['filename']]
            else:
                # unnamed parts are not returned at all.
                continue
            if name in partdict:
                data.seek(0,0)
                partdict[name].append(data)
            else:
                data.seek(0,0)
                partdict[name] = [data]

        fp.seek(rewind) #restore cursor
        return partdict
