// Ghidra headless: -noanalysis -postScript FocusedDecompile.java OUTPUT VA...
// Creates only requested function seeds in the disposable analysis project.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;
import java.util.*;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

public class FocusedDecompile extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<Address> seeds=new ArrayList<>();
        for(int i=1;i<args.length;i++) seeds.add(toAddr(args[i]));
        Set<Address> seen=new HashSet<>();
        List<Address> queue=new ArrayList<>(seeds);
        for(int depth=0;depth<3;depth++) {
            List<Address> next=new ArrayList<>();
            for(Address address:queue) {
                if(!seen.add(address) || !currentProgram.getMemory().contains(address)) continue;
                Function function=getFunctionAt(address);
                if(function==null) {disassemble(address); function=createFunction(address,null);}
                if(function==null) continue;
                InstructionIterator instructions=currentProgram.getListing().getInstructions(function.getBody(),true);
                while(instructions.hasNext()) {
                    Instruction ins=instructions.next();
                    if(ins.getFlowType().isCall()) for(Address target:ins.getFlows()) next.add(target);
                    if(ins.getMnemonicString().equals("RET")) {
                        if(ins.getNumOperands()==0) function.setStackPurgeSize(0);
                        else if(ins.getScalar(0)!=null) function.setStackPurgeSize((int)ins.getScalar(0).getUnsignedValue());
                    }
                }
            }
            queue=next;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[0], "UTF-8")) {
            for (int i=1;i<args.length;i++) {
                Address address=toAddr(args[i]);
                Function function=getFunctionContaining(address);
                if(function==null) { disassemble(address); function=createFunction(address,null); }
                out.println("// REQUEST " + args[i]);
                if(function==null) {out.println("// NO FUNCTION"); continue;}
                DecompileResults result=decompiler.decompileFunction(function,60,monitor);
                if(result.decompileCompleted()) out.println(result.getDecompiledFunction().getC());
                else out.println("// " + result.getErrorMessage());
                out.flush();
            }
        } finally { decompiler.dispose(); }
    }
}
