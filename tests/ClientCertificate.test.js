const assert = require("node:assert/strict")
const { execFileSync, spawn } = require("node:child_process")
const fs = require("node:fs")
const https = require("node:https")
const os = require("node:os")
const path = require("node:path")
const test = require("node:test")

// The Bitwarden CLI fetches through node-fetch 2, which calls https.request
// without an agent, so Node's default HTTPS agent carries the certificate.
// The child below makes that same kind of request against a server that
// rejects every handshake without a client certificate.
const helper = path.join(__dirname, "..", "tools", "client-certificate.cjs")
const dir = fs.mkdtempSync(path.join(os.tmpdir(), "omawarden-mtls-"))
const file = name => path.join(dir, name)

function openssl(...args) {
  execFileSync("openssl", args, { stdio: "ignore" })
}

function certificate(name, subject, extensions) {
  openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", subject, "-keyout", file(`${name}.key`), "-out", file(`${name}.csr`))
  const extra = extensions ? ["-extfile", file(extensions)] : []
  openssl("x509", "-req", "-in", file(`${name}.csr`), "-CA", file("ca.pem"), "-CAkey", file("ca.key"), "-CAcreateserial",
    "-days", "1", ...extra, "-out", file(`${name}.crt`))
  fs.chmodSync(file(`${name}.key`), 0o600)
}

openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=Test CA", "-keyout", file("ca.key"), "-out", file("ca.pem"))
fs.writeFileSync(file("san.ext"), "subjectAltName=DNS:localhost\n")
certificate("server", "/CN=localhost", "san.ext")
certificate("client", "/CN=omawarden-client")
fs.writeFileSync(file("client.pem"), fs.readFileSync(file("client.crt")) + fs.readFileSync(file("client.key")), { mode: 0o600 })
fs.copyFileSync(file("client.crt"), file("loose.pem"))
fs.appendFileSync(file("loose.pem"), fs.readFileSync(file("client.key")))
fs.chmodSync(file("loose.pem"), 0o644)
fs.copyFileSync(file("client.crt"), file("certificate-only.pem"))
fs.chmodSync(file("certificate-only.pem"), 0o600)
openssl("pkey", "-in", file("client.key"), "-aes256", "-passout", "pass:x", "-out", file("encrypted.key"))
fs.chmodSync(file("encrypted.key"), 0o600)

let server
test.before(async () => {
  server = https.createServer({
    cert: fs.readFileSync(file("server.crt")),
    key: fs.readFileSync(file("server.key")),
    ca: fs.readFileSync(file("ca.pem")),
    requestCert: true,
    rejectUnauthorized: true,
  }, (request, response) => {
    response.end(request.socket.getPeerCertificate().subject.CN)
  })
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve))
})
test.after(() => {
  server.close()
  fs.rmSync(dir, { recursive: true, force: true })
})

function request(env) {
  const script = `require("node:https").get("https://localhost:${server.address().port}/api/config", response => {
    let body = ""
    response.on("data", chunk => { body += chunk })
    response.on("end", () => process.stdout.write(body))
  }).on("error", error => { process.stderr.write(error.code || error.message); process.exit(1) })`
  const child = spawn(process.execPath, ["-e", script], {
    env: { PATH: process.env.PATH, NODE_EXTRA_CA_CERTS: file("ca.pem"), NODE_OPTIONS: `--require=${helper}`, ...env },
  })
  let stdout = "", stderr = ""
  child.stdout.on("data", chunk => { stdout += chunk })
  child.stderr.on("data", chunk => { stderr += chunk })
  return new Promise(resolve => child.on("close", status => resolve({ status, stdout, stderr })))
}

test("a combined PEM file is presented on default-agent requests", async () => {
  const result = await request({ OMAWARDEN_CLIENT_CERT: file("client.pem") })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, "omawarden-client")
})

test("the key may sit in its own file", async () => {
  const result = await request({ OMAWARDEN_CLIENT_CERT: file("client.crt"), OMAWARDEN_CLIENT_KEY: file("client.key") })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, "omawarden-client")
})

test("without the preload the server refuses the handshake", async () => {
  const result = await request({ NODE_OPTIONS: "" })
  assert.equal(result.status, 1)
  assert.equal(result.stdout, "")
})

for (const [name, env, message] of [
  ["an unset certificate", {}, /OMAWARDEN_CLIENT_CERT is not set/],
  ["a missing file", { OMAWARDEN_CLIENT_CERT: file("missing.pem") }, /ENOENT/],
  ["a key others can read", { OMAWARDEN_CLIENT_CERT: file("loose.pem") }, /readable only by you/],
  ["a certificate without its key", { OMAWARDEN_CLIENT_CERT: file("certificate-only.pem") }, /no PEM private key/],
  ["a passphrase-protected key", { OMAWARDEN_CLIENT_CERT: file("client.crt"), OMAWARDEN_CLIENT_KEY: file("encrypted.key") }, /passphrase-protected/],
  ["a key from another certificate", { OMAWARDEN_CLIENT_CERT: file("client.crt"), OMAWARDEN_CLIENT_KEY: file("server.key") }, /mismatch/],
]) {
  test(`${name} stops the CLI before it connects`, async () => {
    const result = await request(env)
    assert.equal(result.status, 78)
    assert.match(result.stderr, message)
    assert.equal(result.stdout, "")
  })
}
