const http = require("http");
const fs = require("fs");
const path = require("path");

const root = __dirname;
const types = {
  ".html": "text/html",
  ".css": "text/css",
  ".js": "application/javascript",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".mp4": "video/mp4",
  ".json": "application/json",
  ".xml": "application/xml",
};

http
  .createServer((req, res) => {
    let filePath = path.join(root, req.url === "/" ? "/index.html" : req.url.split("?")[0]);
    if (!path.extname(filePath)) filePath += ".html";

    const ext = path.extname(filePath);
    res.setHeader("Content-Type", types[ext] || "application/octet-stream");

    const stream = fs.createReadStream(filePath);
    stream.on("error", () => {
      res.writeHead(404);
      res.end("Not found");
    });
    stream.pipe(res);
  })
  .listen(5199, () => {
    console.log("http://127.0.0.1:5199/index.html");
  });
