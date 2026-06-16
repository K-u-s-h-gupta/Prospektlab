const http = require('http');
const fs = require('fs');
const path = require('path');

const mime = {
  'html': 'text/html',
  'js': 'text/javascript',
  'css': 'text/css',
  'png': 'image/png',
  'jpg': 'image/jpeg',
  'gif': 'image/gif',
  'svg': 'image/svg+xml',
  'ico': 'image/x-icon'
};

const dir = __dirname;
const port = 8000;

http.createServer((req, res) => {
  let file = req.url === '/' ? '/widget.html' : req.url;
  let filePath = path.join(dir, file);
  
  if (fs.existsSync(filePath)) {
    const ext = path.extname(filePath).slice(1) || 'html';
    res.writeHead(200, {
      'Content-Type': mime[ext] || 'application/octet-stream',
      'Access-Control-Allow-Origin': '*'
    });
    fs.createReadStream(filePath).pipe(res);
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
}).listen(port, () => {
  console.log(`Server running at http://localhost:${port}/widget.html`);
});