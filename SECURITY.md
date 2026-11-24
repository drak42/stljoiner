# Security

## Reporting a problem

Please report security problems privately through GitHub:
[Report a vulnerability](https://github.com/drak42/stljoiner/security/advisories/new)
(the **Security** tab of the repository). Don't open a public issue for them.

Include what you found, how to reproduce it, and which version of stljoiner
(`stljoiner --version`) it affects. You'll get a reply as soon as possible,
and fixes are released as a new version on PyPI and GitHub.

## Supported versions

Only the latest release receives fixes. Upgrade with `pipx upgrade stljoiner`.

## What stljoiner touches

Useful context when judging a problem:

- The command line reads the STL files you name and writes only the output
  file (and `--export-parts` folder) you choose.
- The web interface (`stljoiner web`) keeps uploaded parts in memory only.
  Nothing is written to disk, and exports are sent straight to your browser.
- By default it listens on `127.0.0.1` only and answers only to the host
  names `localhost` and `127.0.0.1`, which guards against DNS rebinding.
- It has **no login**. Starting it with `stljoiner web --host` set to another
  address (for example `0.0.0.0`) lets anyone who can reach that address use
  it, and turns off the host-name check. It prints a warning when you do.
- The page loads three.js from the jsDelivr CDN.
- A way for another website, or another user on the computer, to make the
  default (`127.0.0.1`) server act is a security problem worth reporting.
