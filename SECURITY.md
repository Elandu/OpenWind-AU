# Security Policy

OpenWind-AU is an early-stage open-source project for preliminary terrain and topographic
screening. Please report security issues responsibly.

## Supported Versions

The active `main` branch is the only supported development line until formal releases are tagged.

## Reporting A Vulnerability

Please do not open a public issue for security-sensitive reports.

Instead, contact the maintainer privately through GitHub profile contact options or open a private
security advisory if available.

Include:

- affected version or commit;
- steps to reproduce;
- potential impact;
- whether the issue exposes private data, filesystem access, network access, or arbitrary code
  execution;
- any suggested mitigation.

## Sensitive Data

Do not include private client, project, claim, property-owner, API key, or credential data in
public issues, validation examples, screenshots, or reports.

## Engineering Safety

Incorrect terrain or topographic outputs can affect engineering judgement. Report suspected
calculation, DEM, geocoding, or report-generation errors as bugs with enough evidence to reproduce
the issue. These are product-safety issues even when they are not software security vulnerabilities.
