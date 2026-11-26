// Ghidra script: -preScript/-postScript ApplySymbols.java SYMBOLS.tsv
// Rows from tools/reverse/gen_symbols.py: address, name, kind (function|label), source.
// Pre-analysis it seeds functions so auto-analysis starts from real code;
// post-analysis it reapplies the names (analysis may have created defaults).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;

public class ApplySymbols extends GhidraScript {
    public void run() throws Exception {
        String path = getScriptArgs()[0];
        int functions = 0, labels = 0, failed = 0;
        try (BufferedReader in = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = in.readLine()) != null) {
                String[] f = line.split("\t");
                if (f.length < 3) continue;
                Address a = toAddr(Long.parseLong(f[0], 16));
                if (!currentProgram.getMemory().contains(a)) { failed++; continue; }
                String name = f[1].replaceAll("[^A-Za-z0-9_:]", "_");
                try {
                    if (f[2].equals("function")) {
                        Function fn = getFunctionAt(a);
                        if (fn == null) {
                            if (getInstructionAt(a) == null) disassemble(a);
                            fn = createFunction(a, null);
                        }
                        if (fn != null) {
                            fn.setName(name.replace("::", "__"), SourceType.USER_DEFINED);
                            if (f.length > 3) setPlateComment(a, "symbol source: " + f[3]);
                            functions++;
                        } else failed++;
                    } else {
                        createLabel(a, name.replace("::", "__"), true, SourceType.USER_DEFINED);
                        labels++;
                    }
                } catch (Exception e) { failed++; }
            }
        }
        println(String.format("ApplySymbols: %d functions, %d labels, %d failed", functions, labels, failed));
    }
}
