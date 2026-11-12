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
  document:{getElementById:id => elements[id], createElement:() => ({children:[], appendChild(child) { this.children.push(child); }, addEventListener(name, fn) { this[name] = fn; }, dataset:{}})},
  openCorrection: id => { context.opened = id; },
  filterReconciliation: items => items,
  searchSuggestions: () => [], updateSearchSuggestions: () => {},
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
context.reconciliationItems = [{status:'A_VERIFIER', achat_invoice_id:12, vente_invoice_id:34}, {status:'A_VERIFIER', achat_invoice_id:null}];
elements.recList.children = [];
context.renderReconciliationList();
assert.equal(elements.recList.children[0].children.length, 2);
elements.recList.children[0].children[1].click();
assert.equal(context.opened, 34);
assert.equal(elements.recList.children[1].children.length, 0);
const labelStart = html.indexOf('        function groupedInvoiceLabel(');
const labelEnd = html.indexOf('        function showCompareError(', labelStart);
vm.runInContext(html.slice(labelStart, labelEnd), context);
assert.equal(context.groupedInvoiceLabel(' FAC-1 ', 1, 'Sans achat'), 'FAC-1');
for (const value of ['—', '', '  ', null, undefined]) {
  assert.equal(context.groupedInvoiceLabel(value, 12, 'Sans achat'), '#12');
  assert.equal(context.groupedInvoiceLabel(value, null, 'En attente'), 'En attente');
}
assert.equal(context.groupedInvoiceLabel('—', 0, 'Sans achat'), '#0');
console.log('Tests des statuts, corrections et libellés réussis.');
