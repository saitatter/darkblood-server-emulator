// Ghidra script: -process -noanalysis -postScript ApplyStubNames.java STUB_NAMES.tsv
// Rows from tools/resolve_stubs.py: old_target, module!export, sites, agreement.
// The targets lie outside the image, so this creates uninitialized 64 KiB
// blocks ("stubs_XXXXXXXX") covering them, then a named function at each
// target (MSVC names demangled when possible) so pseudocode shows e.g.
// std::basic_string<...>::~basic_string instead of func_0x600ff3b0.
import ghidra.app.script.GhidraScript;
import ghidra.app.util.demangler.DemangledObject;
import ghidra.app.util.demangler.DemanglerUtil;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.address.AddressSet;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.List;
import java.util.TreeSet;

public class ApplyStubNames extends GhidraScript {
    public void run() throws Exception {
        String path = getScriptArgs()[0];
        Memory mem = currentProgram.getMemory();
        java.util.List<String[]> rows = new java.util.ArrayList<>();
        TreeSet<Long> pages = new TreeSet<>();
        try (BufferedReader in = new BufferedReader(new FileReader(path))) {
            String line;
            while ((line = in.readLine()) != null) {
                String[] f = line.split("\t");
                if (f.length < 2 || f[0].equals("old_target")) continue;
                rows.add(f);
                pages.add(Long.parseLong(f[0], 16) & ~0xFFFFL);
            }
        }
        int blocks = 0;
        for (long page : pages) {
            Address a = toAddr(page);
            if (mem.contains(a)) continue;
            mem.createUninitializedBlock(String.format("stubs_%08x", page), a, 0x10000, false);
            blocks++;
        }
        int named = 0, demangled = 0;
        for (String[] f : rows) {
            Address a = toAddr(Long.parseLong(f[0], 16));
            String[] parts = f[1].split("!", 2);
            String module = parts[0].replace(".", "_");
            String symbol = parts.length > 1 ? parts[1] : f[1];
            String name = symbol;
            try {
                List<DemangledObject> objs = DemanglerUtil.demangle(currentProgram, symbol, a);
                if (objs != null && !objs.isEmpty()) {
                    DemangledObject d = objs.get(0);
                    String ns = d.getNamespace() != null ? d.getNamespace().getNamespaceName() + "::" : "";
                    name = ns + d.getName();
                    demangled++;
                }
            } catch (Exception e) { /* keep the raw export name */ }
            name = (module + "__" + name).replaceAll("[^A-Za-z0-9_:<>,~]", "_").replace("::", "__");
            if (name.length() > 180) name = name.substring(0, 180);
            Function fn = getFunctionAt(a);
            if (fn == null) {
                fn = currentProgram.getFunctionManager().createFunction(
                        null, a, new AddressSet(a, a), SourceType.USER_DEFINED);
            }
            if (fn != null) {
                fn.setName(name, SourceType.USER_DEFINED);
                setPlateComment(a, "protector stub target: " + f[1] + " (" + f[2] + " call sites)");
                named++;
            }
        }
        println(String.format("ApplyStubNames: %d blocks, %d functions (%d demangled)", blocks, named, demangled));
    }
}
