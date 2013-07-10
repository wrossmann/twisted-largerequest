# initial code is taken from:
# http://twistedmatrix.com/documents/12.2.0/web/howto/web-in-60/handling-posts.html

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor
# import LargeRequest
from largerequest import LargeRequest

import cgi

class FormPage(Resource):
    def render_GET(self, request):
        return """
<html>
<body>
<form method="POST" enctype="multipart/form-data">
<input name="the-file" type="file" />
<input type="submit" />
</form>
</body>
</html>
"""

    def render_POST(self, request):
        return '<html><body>You submitted file: %s<pre>%s</pre></body></html>' % (
            # filename always placed in fieldname_filename
            request.args["the-file_filename"][0],
            # remember to treat the args as files/tempfiles now!
            cgi.escape(request.args["the-file"][0].read())
            )

root = Resource()
root.putChild("form", FormPage())
factory = Site(root)
## change to LargeRequest
factory.requestFactory = LargeRequest
reactor.listenTCP(8880, factory)
reactor.run()
