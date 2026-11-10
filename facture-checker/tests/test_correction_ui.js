// Exécuter avec : node tests/test_correction_ui.js
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../web/templates/index.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(match => match[1]);
for (const script of scripts) new vm.Script(script);
const start = html.indexOf('        function renderReconciliationList()');
const end = html.indexOf('        // GESTION & SUPPRESSION', start);
assert.ok(start >= 0 && end > start);
const elements = {
  recList: {innerHTML:'', children:[], appendChild(child) { this.children.push(child); }},
  recSearch: {value:''}, recSupplierSearch: {value:''}, recSort:{value:'original'}, recResultCount:{}
};
const context = vm.createContext({
  reconciliationItems: ['RAPPROCHE', 'RAPPROCHE_PROBABLE', 'ACHAT_EN_ATTENTE', 'A_VERIFIER', 'NOUVEAU'].map(status => ({status, serial_number:'<img src=x>', diagnostic:'<script>danger</script>'})),
  document:{getElementById:id => elements[id], createElement:() => ({})},
  filterReconciliation: items => items,
  escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
});
vm.runInContext(html.slice(start, end), context);
context.renderReconciliationList();
const output = elements.recList.children.map(child => child.innerHTML);
assert.match(output[0], /Rapproché — numéro exact/);
assert.match(output[1], /Correspondance probable — à confirmer/);
assert.match(output[2], /Achat en attente de vente/);
assert.match(output[3], /À vérifier/);
assert.match(output[4], /Statut inconnu — à vérifier/);
assert.ok(output.every(row => !row.includes('<script>') && !row.includes('<img src=x>')));
console.log('Tests des statuts et de l’échappement réussis.');
