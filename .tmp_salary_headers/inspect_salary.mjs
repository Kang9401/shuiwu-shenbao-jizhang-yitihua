import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const source = process.argv[2];
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 12000 });
console.log("SHEETS");
console.log(sheets.ndjson);

const records = String(sheets.ndjson || "")
  .split(/\r?\n/)
  .filter(Boolean)
  .map((line) => {
    try { return JSON.parse(line); } catch { return null; }
  })
  .filter(Boolean);
const names = [...new Set(records.map((row) => row.name || row.sheetName).filter(Boolean))];
for (const name of names) {
  const region = await workbook.inspect({
    kind: "region",
    sheetId: name,
    range: "A1:ZZ8",
    include: "values,formulas",
    maxChars: 50000,
    tableMaxRows: 8,
    tableMaxCols: 702,
    tableMaxCellChars: 160,
  });
  console.log(`REGION ${name}`);
  console.log(region.ndjson);
}
