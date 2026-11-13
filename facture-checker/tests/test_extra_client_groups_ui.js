// Exécuter avec : node tests/test_extra_client_groups_ui.js
// DOM simulé : les gestionnaires et la logique métier sont extraits du template réel.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../web/templates/index.html'), 'utf8');
function excerpt(start, end) {
    const from = html.indexOf(start);
    const to = html.indexOf(end, from + start.length);
    assert.ok(from >= 0 && to > from, `fonctions introuvables : ${start}`);
    return html.slice(from, to);
}

class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.children = []; this.style = {}; this.files = []; this.value = '';
        this.textContent = ''; this.listeners = {}; this.className = '';
        this.classList = {
            add: name => { if (!this.className.split(/\s+/).includes(name)) this.className += ` ${name}`; },
            remove: name => { this.className = this.className.split(/\s+/).filter(c => c !== name).join(' '); },
            contains: name => this.className.split(/\s+/).includes(name),
        };
    }
    // Le gabarit statique de carte est interprété pour exposer ses éléments et attributs.
    set innerHTML(markup) {
        this.replaceChildren();
        const tags = markup.matchAll(/<(div|button|input)\b([^>]*)>/g);
        for (const [, tag, attributes] of tags) {
            const child = new Element(tag);
            for (const [, key, value] of attributes.matchAll(/([\w-]+)="([^"]*)"/g)) child[key === 'class' ? 'className' : key] = value;
            child.multiple = /(?:^|\s)multiple(?:\s|$)/.test(attributes);
            this.appendChild(child);
        }
    }
    appendChild(child) { child.parent = this; this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.append(...children); }
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; } }
    setAttribute(name, value) { this[name] = value; }
    querySelector(selector) { assert.ok(selector.startsWith('.')); return descendants(this).find(el => el.className.split(/\s+/).includes(selector.slice(1))) || null; }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    dispatch(type, event = {}) {
        event.preventDefault ||= () => { event.defaultPrevented = true; };
        event.stopPropagation ||= () => { event.propagationStopped = true; };
        for (const listener of this.listeners[type] || []) listener(event);
        if (this[`on${type}`]) this[`on${type}`](event);
        return event;
    }
    click() { this.clicks = (this.clicks || 0) + 1; this.dispatch('click'); }
}
function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }
class RecordingFormData {
    constructor() { this.entries = []; }
    append(name, value) { this.entries.push([name, value]); }
}

async function main() {
    const ids = Object.fromEntries(['extraClientGroups', 'comparisonInputs', 'compareError', 'btnLaunchCompare', 'groupedCompareResult', 'compareResultBox', 'compareLoadingBox', 'compareLoadingStep'].map(id => [id, new Element('div')]));
    const document = { createElement: tag => new Element(tag), getElementById: id => { assert.ok(ids[id], `élément inconnu : ${id}`); return ids[id]; } };
    const requests = [], alerts = [];
    let failRequest = false;
    let result = {complete: false, groups: [], warnings: []};
    const context = vm.createContext({
        document, FormData: RecordingFormData,
        FileReader: class { readAsDataURL(file) { this.onload({target: {result: `data:${file.name}`}}); } },
        alert: message => alerts.push(message),
        fetch: async (url, options) => { requests.push({url, ...options}); if (failRequest) throw new Error('réseau'); return {}; },
        readApiResponse: async () => result,
        cleanupDocumentPreviewUrls() {}, addDocumentPreview() {}, updateInvoiceCountBadge() {}, renderComparisonResult() {},
        setInterval, clearInterval,
    });
    vm.runInContext('let vendorFiles = []; let clientFiles = [];', context);
    vm.runInContext(excerpt('        function isAcceptedFile(', '        function handleFilesAddedToSingle('), context);
    vm.runInContext(excerpt('        function attachDropZone(', '        function setupDragAndDrop('), context);
    vm.runInContext(excerpt('        const extraClientGroups = [];', '        function showArchivedDocuments('), context);
    const setFiles = (vendor, client) => { context.testVendor = vendor; context.testClient = client; vm.runInContext('vendorFiles = testVendor; clientFiles = testClient;', context); };
    const cards = () => ids.extraClientGroups.children;
    const select = (card, selector, files) => { const input = card.querySelector(selector); assert.ok(input); input.files = files; input.value = 'selected'; input.dispatch('change'); assert.equal(input.value, ''); };
    const vendor = [{name: 'achat-1.pdf'}, {name: 'achat-2.jpg'}];
    const primary = [{name: 'client-1.pdf'}, {name: 'client-2.jpg'}];
    const a = [{name: 'a1.jpg', type: 'image/jpeg'}, {name: 'a2.pdf', type: 'application/pdf'}];
    const b = [{name: 'b.pdf', type: 'application/pdf'}];
    const invalid = {name: 'malware.exe', type: 'application/octet-stream'};

    // Trois cartes indépendantes ; les boutons ouvrent leurs vrais inputs.
    context.addClientGroup(); context.addClientGroup(); context.addClientGroup();
    assert.equal(cards().length, 3);
    for (const card of cards()) {
        for (const selector of ['.extra-file', '.extra-file-add']) {
            assert.equal(card.querySelector(selector).multiple, true);
            assert.match(card.querySelector(selector).accept, /pdf/i);
            assert.match(card.querySelector(selector).accept, /image/i);
        }
    }
    const [first, middle, last] = [...cards()];
    first.querySelector('.extra-import').click();
    assert.equal(first.querySelector('.extra-file').clicks, 1);
    first.querySelector('.extra-add-photo').click();
    assert.equal(first.querySelector('.extra-camera-add').clicks, 1);
    select(first, '.extra-file', [a[0], invalid]);
    select(first, '.extra-file-add', [a[1]]);
    select(middle, '.extra-camera', [{name: 'milieu.jpg'}]);
    select(last, '.extra-file', b);
    assert.equal(first.querySelector('.zone-badge').textContent, '2 pages');
    assert.equal(first.querySelector('.zone-preview-grid').children.length, 2);
    // Suppression d'une page puis ajout ; sélection initiale remplace, ajout conserve.
    first.querySelector('.zone-preview-grid').children[0].querySelector('.btn-remove-page').click();
    assert.equal(first.querySelector('.zone-badge').textContent, '1 page');
    select(first, '.extra-file', [a[0]]);
    select(first, '.extra-file-add', [a[1]]);
    middle.querySelector('.extra-remove').click();
    assert.deepEqual(cards(), [first, last]);

    // Dépôt réel via les listeners : rejet des formats non supportés et ajout des fichiers valides.
    const enter = last.dispatch('dragenter');
    assert.ok(enter.defaultPrevented && enter.propagationStopped && last.classList.contains('drag-over'));
    const transfer = {files: [invalid, {name: 'depot.png', type: 'image/png'}]};
    last.dispatch('dragover', {dataTransfer: transfer});
    assert.equal(transfer.dropEffect, 'copy');
    last.dispatch('drop', {dataTransfer: transfer});
    assert.equal(last.classList.contains('drag-over'), false);
    assert.equal(last.querySelector('.zone-badge').textContent, '2 pages');
    last.dispatch('drop', {dataTransfer: {files: [invalid]}});
    assert.match(alerts[0], /format non supporté/i);
    assert.equal(last.querySelector('.zone-badge').textContent, '2 pages');

    setFiles([], primary); await context.uploadAndCompare();
    assert.match(ids.compareError.textContent, /fournisseur/i);
    setFiles(vendor, []); await context.uploadAndCompare();
    assert.match(ids.compareError.textContent, /client/i);
    setFiles(vendor, primary); context.addClientGroup(); await context.uploadAndCompare();
    assert.match(ids.compareError.textContent, /groupe vide/i);
    assert.equal(requests.length, 0);
    cards()[2].querySelector('.extra-remove').click();

    // FormData réindexé, réponse incomplète, puis reprise sans perdre les groupes.
    result = {complete: false, groups: [{group: 'client_1', status: 'ok', invoice_id: 42, reused: true}, {group: 'client_2', status: 'error', error: 'échec'}], warnings: ['Attention']};
    await context.uploadAndCompare();
    assert.equal(ids.compareError.textContent, '');
    assert.equal(requests[0].url, '/api/compare-grouped');
    assert.equal(requests[0].method, 'POST');
    const expected = [
        ['vendor_files', vendor[0]], ['vendor_files', vendor[1]],
        ['client_0', primary[0]], ['client_0', primary[1]],
        ['client_1', a[0]], ['client_1', a[1]], ['client_2', b[0]], ['client_2', transfer.files[1]],
    ];
    assert.deepEqual(requests[0].body.entries, expected);
    const lines = ids.groupedCompareResult.children.map(child => child.textContent).join('\n');
    assert.match(lines, /reprendre/i); assert.match(lines, /réutilisée/); assert.match(lines, /échec/); assert.match(lines, /Attention/);
    assert.equal(ids.btnLaunchCompare.disabled, false);
    failRequest = true; await context.uploadAndCompare();
    assert.match(ids.groupedCompareResult.textContent, /réseau/);
    assert.equal(ids.btnLaunchCompare.disabled, false);
    failRequest = false; await context.uploadAndCompare();
    assert.deepEqual(requests[1].body.entries, expected);
    assert.deepEqual(requests[2].body.entries, expected);
    assert.equal(first.querySelector('.zone-badge').textContent, '2 pages');
    assert.equal(last.querySelector('.zone-badge').textContent, '2 pages');

    [...cards()].forEach(card => card.querySelector('.extra-remove').click());
    await context.uploadAndCompare();
    const legacy = requests.at(-1);
    assert.equal(legacy.url, '/api/compare');
    assert.deepEqual(legacy.body.entries, [
        ['vendor_files', vendor[0]], ['vendor_files', vendor[1]],
        ['client_files', primary[0]], ['client_files', primary[1]],
    ]);
    console.log('Tests des groupes client supplémentaires réussis.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
