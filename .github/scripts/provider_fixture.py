import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

class Fixture(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length',0)))
        if self.path == '/token':
            fields = parse_qs(body.decode())
            assert fields['client_id']==['qa-only-client'] and fields['client_secret']==['qa-only-demo']
            assert fields['grant_type']==['client_credentials'] and fields['scope']==['openid']
            reply={'access_token':'local-only','token_type':'Bearer','expires_in':3600}
        elif self.path == '/consult/getArticle':
            assert self.headers.get('Authorization') == 'Bearer local-only'
            article = json.loads(body)['id']
            assert article=='LEGIARTI000049320039'
            reply={'article':{'id':article}}
        else:
            return self.send_error(404)
        data=json.dumps(reply).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

HTTPServer(('127.0.0.1',5689),Fixture).serve_forever()
