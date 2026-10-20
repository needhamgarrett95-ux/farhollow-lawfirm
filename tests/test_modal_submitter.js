// Regression test for the v2.4.3 modalConfirmSubmit fix (Bug 1):
// confirming a modal must submit the form WITH the clicked button's
// name/value (payroll's action=generate) — plain form.submit() drops it.
// Requires jsdom:  npm install jsdom   (run from a dir containing it)
// Run:  node tests/test_modal_submitter.js
const { JSDOM } = require('jsdom');
const fs = require('fs');
const dom = new JSDOM(`<!DOCTYPE html><body>
  <form id="gen" method="post" onsubmit="return modalConfirmSubmit(this, 'Generate?', {title:'Generate paychecks', confirmText:'Generate', danger:true});">
    <input type="hidden" name="period_start" value="2026-10-18">
    <button type="submit" name="action" value="generate" id="genBtn">Generate paychecks</button>
  </form>
  <form id="del" method="post" onsubmit="return modalConfirmSubmit(this, 'Delete?');">
    <input type="hidden" name="csrf_token" value="x">
    <button type="submit" id="delBtn">Delete</button>
  </form>
</body>`, { runScripts: "dangerously", url: "http://localhost/" });

const { window } = dom;

let submissions = [];
window.HTMLFormElement.prototype.requestSubmit = function (submitter) {
  const ev = new window.Event('submit', { bubbles: true, cancelable: true });
  const proceed = this.dispatchEvent(ev);
  if (proceed) {
    submissions.push({ form: this.id,
      submitterName: (submitter && submitter.form === this) ? submitter.name : null,
      submitterValue: (submitter && submitter.form === this) ? submitter.value : null,
      via: 'requestSubmit' });
  }
};
// Emulate a real user click on a submit button: capture-phase document
// listener (from modal.js) must see the click BEFORE the browser's default
// action fires the submit event — same order as a real browser.
function clickSubmit(btnId) {
  const btn = window.document.getElementById(btnId);
  const form = btn.form;
  // stop jsdom's broken internal default action (its requestSubmit stub throws)
  btn.addEventListener('click', (e) => e.preventDefault(), { once: true });
  btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  form.requestSubmit(btn);   // the browser's default action, now driven manually
}
window.eval(fs.readFileSync("/home/hatch/workspace/lawfirm/static/modal.js", "utf8"));

const modalButtons = () => window.document.querySelectorAll('.modal-actions button');
const wait = (ms) => new Promise(r => setTimeout(r, ms));

async function main() {
  clickSubmit('genBtn');
  await wait(100);
  let btns = modalButtons();
  if (!btns.length) { console.log('FAIL: modal did not open'); process.exit(1); }
  btns[btns.length - 1].click(); // Confirm ("Generate")
  await wait(100);
  const g = submissions.find(s => s.form === 'gen');
  console.log('generate submission:', JSON.stringify(g));
  if (g && g.submitterName === 'action' && g.submitterValue === 'generate' && g.via === 'requestSubmit') {
    console.log('PASS: generate carries action=generate via requestSubmit');
  } else { console.log('FAIL: generate missing action=generate'); process.exit(1); }

  submissions = [];
  clickSubmit('delBtn');
  await wait(100);
  btns = modalButtons();
  btns[0].click(); // Cancel
  await wait(50);
  if (submissions.length === 0) console.log('PASS: cancel submits nothing');
  else { console.log('FAIL: cancel submitted', JSON.stringify(submissions)); process.exit(1); }

  submissions = [];
  clickSubmit('delBtn');
  await wait(100);
  btns = modalButtons();
  btns[btns.length - 1].click(); // Confirm
  await wait(100);
  if (submissions.length === 1) console.log('PASS: exactly one submission, no modal loop');
  else { console.log('FAIL: expected 1 submission, got', JSON.stringify(submissions)); process.exit(1); }

  submissions = [];
  clickSubmit('genBtn');
  await wait(100);
  if (modalButtons().length) console.log('PASS: modal reopens on subsequent submit');
  else { console.log('FAIL: modal did not reopen'); process.exit(1); }

  console.log('ALL MODAL TESTS PASSED');
}
main();
