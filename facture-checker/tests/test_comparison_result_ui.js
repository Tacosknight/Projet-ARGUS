// Exécuter avec : node tests/test_comparison_result_ui.js
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../web/templates/index.html'), 'utf8');
const start = html.indexOf('        function formatCompareAmount(value');
const end = html.indexOf('        function resetComparison()', start);
assert.ok(start >= 0 && end > start);
function element() {
    return { children: [], style: {}, classList: { add() {} }, appendChild(child) { this.children.push(child); }, replaceChildren(...children) { this.children = children; }, scrollIntoView() {} };
}
const elements = {};
const context = vm.createContext({
    document: { getElementById(id) { return elements[id] ||= element(); }, createElement: element },
    showExtractionPages() {}, showArchivedDocuments() {},
});
vm.runInContext(html.slice(start, end), context);
context.renderComparisonResult({ global_status: 'WARNING', ecart_ttc: 50, vendor_invoice: {montant_ttc: 100}, client_invoice: {montant_ttc: 150}, rows: [
    {status: 'WARNING', label: 'Produit', detail: 'À confirmer'},
    {status: 'ERROR', label: '<script>', detail: 'Divergent'},
    {status: 'MATCH', label: 'Date'},
] });
let items = elements.compareReviewContent.children[0].children;
assert.equal(items.length, 2);
assert.equal(items[0].textContent, 'Anomalie — <script> : Divergent');
assert.equal(items[0].innerHTML, undefined);
assert.equal(items[1].textContent, 'À vérifier — Produit : À confirmer');
assert.equal(elements.compareMarginVal.innerText, '+50.00 €');
assert.equal(elements.compareMarginVal.style.color, '');
context.renderComparisonResult({global_status: 'MATCH', rows: [{status: 'MATCH', label: 'Date'}]});
assert.match(elements.compareReviewContent.children[0].textContent, /Aucun point/);
assert.equal(elements.compareMarginVal.innerText, '-- €');
context.renderComparisonResult({global_status: 'WARNING', rows: []});
assert.match(elements.compareReviewContent.children[0].textContent, /Consultez le détail/);
assert.ok(html.indexOf('id="compareReviewContent"') < html.indexOf('id="compareTableBody"'));
assert.match(html, /Il ne constitue pas une marge/);
context.renderComparisonResult({global_status: 'WARNING', vendor_invoice: {montant_ttc: '12.5', serial_numbers: ['<img src=x>']}, client_invoice: {montant_ttc: 'oops'}, ecart_ttc: Infinity, rows: [{status: 'ERROR', category: 'serials', label: '<script>', detail: '<img>', items: [{status: 'WARNING', vendor_sn: '<svg>', client_sn: '<script>', product_name: '<b>'}]}]});
assert.equal(elements.compareVendorTtc.innerText, '12.50 €');
assert.equal(elements.compareClientTtc.innerText, '-- €');
assert.equal(elements.compareMarginVal.innerText, '-- €');
let row = elements.compareTableBody.children[0];
assert.equal(row.children[0].children[0].textContent, '<script>');
assert.equal(row.children[0].children[1].children[0].textContent, ' <img>');
assert.equal(row.children[1].children[0].textContent, 'S/N: <img src=x>');
assert.equal(row.children[2].children[0].children[0].children[0].textContent, '<svg>');
context.renderComparisonResult({rows: []});
assert.match(elements.compareTableBody.children[0].children[0].textContent, /Aucune donnée/);
console.log('Tests de restitution de comparaison réussis.');
