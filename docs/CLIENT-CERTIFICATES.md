# Client certificates (mTLS)

Some self-hosted servers only answer clients that present a TLS client
certificate: Cloudflare's mTLS rules, nginx `ssl_verify_client`, Traefik
`clientAuth` and the like. Without one, the server answers `403` or drops
the connection, and sign-in, unlock or sync fails with a generic error.

The Bitwarden CLI has no client-certificate option. OmaWarden ships a small
preload, [`tools/client-certificate.cjs`](../tools/client-certificate.cjs),
that hands your certificate to the CLI's HTTPS connections. It works with
the Node.js CLI: Arch's `bitwarden-cli` package, which OmaWarden's installer
sets up, or `npm install -g @bitwarden/cli`. The standalone `bw` binary from
bitwarden.com ignores it; see [the end of this page](#standalone-bw-binary).

## 1. Save the certificate

You need one PEM file holding the certificate and its private key, without
a passphrase, readable only by you. From the `.p12` file the mobile apps
use:

```bash
mkdir -p ~/.config/omawarden
openssl pkcs12 -in client.p12 -nodes -out ~/.config/omawarden/client.pem
chmod 600 ~/.config/omawarden/client.pem
```

Older `.p12` files may need `-legacy`. If the certificate and key are
separate PEM files, keep both and point `OMAWARDEN_CLIENT_KEY` at the key in
the next step.

Check that the server accepts it before involving the CLI; a JSON reply
means the certificate works:

```bash
curl --cert ~/.config/omawarden/client.pem https://vault.example.com/api/config
```

## 2. Set the CLI command

Leave **Server URL** at your server's `https://` address. In Settings →
Advanced, set **Bitwarden CLI command** to one line:

```text
env NODE_OPTIONS=--require=/home/you/.config/omarchy/plugins/io.github.salemsayed.omawarden/tools/client-certificate.cjs OMAWARDEN_CLIENT_CERT=/home/you/.config/omawarden/client.pem bw
```

Replace `/home/you` with your home folder. Paths must be absolute: no shell
runs the command, so `~` and `$HOME` are not expanded. With a separate key,
add `OMAWARDEN_CLIENT_KEY=/home/you/.config/omawarden/client.key` before
`bw`.

Or from a terminal:

```bash
omarchy bar set io.github.salemsayed.omawarden cliCommand "env NODE_OPTIONS=--require=$HOME/.config/omarchy/plugins/io.github.salemsayed.omawarden/tools/client-certificate.cjs OMAWARDEN_CLIENT_CERT=$HOME/.config/omawarden/client.pem bw"
```

## 3. Sign in

Choose **Sign in** in the panel as usual.

If the certificate can't be used, the CLI stops before connecting and the
panel says it couldn't read the vault status. Run the same command with
`status` in a terminal to see why:

```bash
env NODE_OPTIONS=--require=$HOME/.config/omarchy/plugins/io.github.salemsayed.omawarden/tools/client-certificate.cjs OMAWARDEN_CLIENT_CERT=$HOME/.config/omawarden/client.pem bw status
# OmaWarden client certificate: /home/you/.config/omawarden/client.pem must be readable only by you (chmod 600 it)
```

## Notes

- The preload only reads the certificate files and sets them on Node's
  default HTTPS agent. Anyone who can read `client.pem` can reach your
  server as you; your vault stays encrypted with your master password.
- To renew the certificate, replace `client.pem` (keep it `chmod 600`).
  The next CLI start uses it; you stay signed in.
- When `https_proxy` or `http_proxy` is set, the CLI connects through its
  own proxy agent and the certificate is not sent.
- A local tunnel serving plain `http://127.0.0.1:…` does not work: the CLI
  refuses server URLs that aren't `https://`. A raw TLS tunnel (stunnel,
  nginx `stream`) also leaves the `Host` header at `127.0.0.1`, which
  Cloudflare and most reverse proxies reject.

## Standalone bw binary

The standalone binary ignores `NODE_OPTIONS`. The simplest fix is to install
the packaged CLI (`sudo pacman -S bitwarden-cli`) and use the command above.

To keep the standalone binary, put a local HTTPS proxy in front of the
server that presents the certificate. With [Caddy](https://caddyserver.com),
running as you:

```caddyfile
{
	admin off
	skip_install_trust
	auto_https disable_redirects
}

https://localhost:8087 {
	bind 127.0.0.1
	tls internal
	reverse_proxy https://vault.example.com {
		header_up Host vault.example.com
		transport http {
			tls_client_auth /home/you/.config/omawarden/client.pem /home/you/.config/omawarden/client.pem
		}
	}
}
```

Set **Server URL** to `https://localhost:8087`, and make the CLI trust
Caddy's local certificate authority:

```text
env NODE_EXTRA_CA_CERTS=/home/you/.local/share/caddy/pki/authorities/local/root.crt /path/to/bw
```

The proxy lets any program on this computer reach your server with your
certificate, so only use it on a single-user machine.
