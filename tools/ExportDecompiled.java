// Ghidra script: -process -noanalysis -postScript ExportDecompiled.java OUTDIR [TIMEOUT_S]
// Writes pseudocode of every function into OUTDIR/<0xNN0000>.c (one file per
// 64 KiB of address space) plus OUTDIR/functions.tsv (address, name, size,
// status). Pseudocode is reconstructed: signatures and types can be wrong.
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.File;
import java.io.PrintWriter;
import java.util.HashMap;
import java.util.Map;

public class ExportDecompiled extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        File dir = new File(args[0]);
        dir.mkdirs();
        int timeout = args.length > 1 ? Integer.parseInt(args[1]) : 30;
        DecompInterface dec = new DecompInterface();
        dec.setOptions(new DecompileOptions());
        dec.openProgram(currentProgram);
        Map<Long, PrintWriter> files = new HashMap<>();
        int total = currentProgram.getFunctionManager().getFunctionCount(), n = 0, ok = 0;
        try (PrintWriter index = new PrintWriter(new File(dir, "functions.tsv"), "UTF-8")) {
            index.println("address\tname\tbytes\tstatus");
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext() && !monitor.isCancelled()) {
                Function fn = it.next();
                long va = fn.getEntryPoint().getOffset();
                long bucket = va & ~0xFFFFL;
                PrintWriter out = files.get(bucket);
                if (out == null) {
                    out = new PrintWriter(new File(dir, String.format("%08x.c", bucket)), "UTF-8");
                    files.put(bucket, out);
                }
                String status;
                DecompileResults r = dec.decompileFunction(fn, timeout, monitor);
                out.println(String.format("// FUNCTION %08x %s", va, fn.getName()));
                if (r.decompileCompleted() && r.getDecompiledFunction() != null) {
                    out.println(r.getDecompiledFunction().getC());
                    status = "ok";
                    ok++;
                } else {
                    out.println("// decompile failed: " + r.getErrorMessage());
                    status = "failed";
                }
                index.println(String.format("%08x\t%s\t%d\t%s", va, fn.getName(),
                        fn.getBody().getNumAddresses(), status));
                if (++n % 2000 == 0) println(String.format("ExportDecompiled: %d/%d", n, total));
            }
        } finally {
            for (PrintWriter w : files.values()) w.close();
            dec.dispose();
        }
        println(String.format("ExportDecompiled: %d functions, %d decompiled", n, ok));
    }
}
