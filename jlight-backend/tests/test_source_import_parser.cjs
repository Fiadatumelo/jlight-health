const assert = require('node:assert/strict')
const fs = require('node:fs')

const html = fs.readFileSync('index.html', 'utf8')
const aliases = html.match(/const SOURCE_IMPORT_ALIASES = \{[\s\S]*?\n\}/)
assert.ok(aliases, 'SOURCE_IMPORT_ALIASES must exist')

const start = html.indexOf('function parseSourceCSV(text) {')
const end = html.indexOf('async function previewSourceCsv()', start)
assert.ok(start >= 0 && end > start, 'parseSourceCSV function boundaries must exist')
const parser = html.slice(start, end)
const parseSourceCSV = new Function(aliases[0] + '\n' + parser + '\nreturn parseSourceCSV')()

const csv = 'patient_id,summary,status\r\nP1,"a, b",open\r\nP2,"said ""yes""",closed'
const parsedCsv = parseSourceCSV(csv)
assert.deepEqual(parsedCsv.headers, ['patientId', 'summary', 'status'])
assert.equal(parsedCsv.rows[0].summary, 'a, b')
assert.equal(parsedCsv.rows[1].summary, 'said "yes"')

const tsv = 'patientId\tstatus\nP1\topen\nP2\tclosed'
const parsedTsv = parseSourceCSV(tsv)
assert.deepEqual(parsedTsv.headers, ['patientId', 'status'])
assert.equal(parsedTsv.rows.length, 2)
assert.equal(parsedTsv.rows[1].status, 'closed')

assert.throws(() => parseSourceCSV('patientId,status\nP1,"open'), /quoted field is not closed/i)
assert.throws(() => parseSourceCSV('patient_id,patientId\nP1,P2'), /map to the same field/i)
assert.throws(() => parseSourceCSV('patientId,status\nP1,open,extra'), /more columns than the header/i)

console.log('JLIGHT source CSV parser tests passed.')
