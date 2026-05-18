#!/usr/bin/env node
const fs = require('fs')
const path = require('path')
const tmpPath = require('os').tmpdir()

async function start() {
  const anonymousTokenPath = path.resolve(tmpPath, 'anonymous_token')
  if (!fs.existsSync(anonymousTokenPath)) {
    fs.writeFileSync(anonymousTokenPath, '', 'utf-8')
  }

  if (process.env.NCM_API_SKIP_ANONYMOUS_TOKEN !== 'true') {
    // Desktop packaging can skip this so the local API listens even when offline.
    const generateConfig = require('./generateConfig')
    await generateConfig()
  }

  require('./server').serveNcmApi({
    checkVersion: process.env.NCM_API_CHECK_VERSION !== 'false',
  })
}

start()
