// Makes the Node.js Bitwarden CLI present a TLS client certificate, for
// servers that require mutual TLS (mTLS). The CLI has no option for this;
// its requests go through Node's default HTTPS agent, which this preload
// configures before the CLI starts. Load it with
//
//   env NODE_OPTIONS=--require=/abs/path/client-certificate.cjs \
//       OMAWARDEN_CLIENT_CERT=/abs/path/client.pem bw ...
//
// OMAWARDEN_CLIENT_CERT is a PEM certificate (chain); its private key may sit
// in the same file or in OMAWARDEN_CLIENT_KEY. The key must be unencrypted
// and readable only by you.

"use strict"

const fs = require("node:fs")
const https = require("node:https")
const tls = require("node:tls")

function fail(message) {
  process.stderr.write(`OmaWarden client certificate: ${message}\n`)
  process.exit(78)
}

const certPath = process.env.OMAWARDEN_CLIENT_CERT || ""
const keyPath = process.env.OMAWARDEN_CLIENT_KEY || certPath

if (!certPath) fail("OMAWARDEN_CLIENT_CERT is not set")

let cert
let key
try {
  if (fs.statSync(keyPath).mode & 0o077) {
    fail(`${keyPath} must be readable only by you (chmod 600 it)`)
  }
  cert = fs.readFileSync(certPath)
  key = fs.readFileSync(keyPath)
  if (!key.includes("PRIVATE KEY-----")) {
    fail(`${keyPath} holds no PEM private key (set OMAWARDEN_CLIENT_KEY)`)
  }
  if (key.includes("ENCRYPTED")) {
    fail(`${keyPath} is passphrase-protected; save it unencrypted with openssl pkey`)
  }
  tls.createSecureContext({ cert, key })
} catch (error) {
  fail(error.message)
}

Object.assign(https.globalAgent.options, { cert, key })
