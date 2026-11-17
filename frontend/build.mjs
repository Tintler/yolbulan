import { readFile, writeFile } from 'node:fs/promises'
import { build } from 'esbuild'

await build({
  entryPoints: ['src/main.jsx'],
  bundle: true,
  minify: true,
  target: 'chrome109',
  outfile: 'assets/app.js',
  legalComments: 'eof',
})

const packages = ['react', 'react-dom', 'scheduler', 'lucide-react']
const licenses = await Promise.all(packages.map(async name =>
  `${name}\n${(await readFile(`node_modules/${name}/LICENSE`, 'utf8')).trim()}\n`))
await writeFile('assets/LICENSLAR.txt', licenses.join('\n'))
