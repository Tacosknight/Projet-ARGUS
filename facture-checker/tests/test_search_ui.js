// Exécuter avec : node tests/test_search_ui.js
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../web/templates/index.html'), 'utf8');
const start = html.indexOf('        function normalizeSearch(value)');
const end = html.indexOf('        let reconciliationItems = null;', start);
assert.ok(start >= 0 && end > start, 'fonctions de recherche introuvables');
const context = vm.createContext({});
vm.runInContext(html.slice(start, end), context);
const invoices = [
    { id: 1, numero_facture: 'A-12', fournisseur_nom: 'Écoute', date_facture: '2025-01-01' },
    { id: 2, numero_facture: 'B-12', fournisseur_nom: 'ECOUTE', date_facture: '02/01/2025' },
    { id: 3, numero_facture: 'A-13', fournisseur_nom: 'Autre', date_facture: '2025-02-30' },
    { id: 4, numero_facture: 'A-14', fournisseur_nom: null, date_facture: null },
    { id: 5, numero_facture: 'A-15', fournisseur_nom: 'Écoute', date_facture: '2025-01-01' },
];
const ids = list => Array.from(list, item => item.id);
assert.deepEqual(ids(context.filterInvoices(invoices, '', '')), [2, 5, 1, 4, 3]);
assert.deepEqual(ids(context.filterInvoices(invoices, 'a-', 'ecoute')), [5, 1]);
assert.deepEqual(ids(context.filterInvoices(invoices, 'inconnu', '')), []);
assert.equal(context.invoiceDateKey('31/02/2025'), null);
const items = [
    { serial_number: 'SN123', fournisseur_nom: 'Écoute', patient_nom: 'Alice', achat_num_facture: 'FAC-9' },
    { serial_number: '—', fournisseur_nom: '—', produit_nom: 'Appareil' },
    { serial_number: 'SN456', fournisseur_nom: 'Autre', patient_nom: 'Alice' },
];
const serials = list => Array.from(list, item => item.serial_number);
assert.deepEqual(serials(context.filterReconciliation(items, 'alice', 'ecoute', 'original')), ['SN123']);
assert.deepEqual(serials(context.filterReconciliation(items, 'fac-9', '', 'original')), ['SN123']);
assert.deepEqual(serials(context.filterReconciliation(items, '', '', 'supplier-asc')), ['SN456', 'SN123', '—']);
assert.deepEqual(serials(context.filterReconciliation(items, '', '', 'supplier-desc')), ['SN123', 'SN456', '—']);
assert.deepEqual(serials(context.filterReconciliation(items, 'absent', '', 'original')), []);
assert.equal(context.filterReconciliation(items, '', '', 'original').length, 3);
console.log('Tests de recherche et de tri réussis.');
