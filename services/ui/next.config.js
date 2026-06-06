/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Disable Next.js built-in gzip compression so SSE / streaming responses
  // are flushed to the browser token-by-token instead of being buffered until
  // the gzip window fills up.  Compression for static assets is handled by the
  // container's reverse proxy (or nginx in front of the Next.js server).
  compress: false,
};

module.exports = nextConfig;
