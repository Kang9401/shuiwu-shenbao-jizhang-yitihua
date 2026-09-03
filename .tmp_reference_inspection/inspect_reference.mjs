import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "E:/办公/claude_code/税务申报记账一体化/个税测试/核对底稿/个税核对底稿 - 20260827-有数据.xlsx";
const outputDir = "E:/办公/claude_code/税务申报记账一体化/.tmp_reference_inspection/renders";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
await fs.mkdir(outputDir, { recursive: true });
const sheets = workbook.worksheets.items;
const summary = [];
for (const sheet of sheets) {
  const used = sheet.getUsedRange();
  const styles = await workbook.inspect({
    kind: "computedStyle",
    sheetId: sheet.name,
    range: used?.address || "A1:Z20",
    maxChars: 5000,
  });
  summary.push({ name: sheet.name, usedRange: used?.address || "", styles: styles.ndjson });
  const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 0.75, format: "png" });
  await fs.writeFile(`${outputDir}/${String(sheets.indexOf(sheet) + 1).padStart(2, "0")}.png`, new Uint8Array(await preview.arrayBuffer()));
}
await fs.writeFile(`${outputDir}/summary.json`, JSON.stringify(summary, null, 2), "utf8");
console.log(JSON.stringify(summary.map(({ name, usedRange }) => ({ name, usedRange }))));
