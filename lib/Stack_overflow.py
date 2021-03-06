import angr
# import claripy
from angr import sim_options as so
from pwn import *
from lib import common_tools as ct
import json

def check_symbolic_bits(state,val):
    bits = 0
    for idx in range(state.arch.bits):
        if val[idx].symbolic:
            bits += 1
    return bits



def print_pc_overflow_msg(state,byte_s):
    
    hists=state.history.bbl_addrs.hardcopy
    paths,print_paths=ct.deal_history(state,hists)
    pc_overflow_maps=state.globals['pc_overflow_maps']
    limit=state.globals['limit']

    if ct.cmp_path(paths,pc_overflow_maps,limit):

        path_dir={'pc_overflow_result':{}}
        path_dir['pc_overflow_result']['over_num']=hex(byte_s)
        path_dir['pc_overflow_result']['stdin']=str(state.posix.dumps(0))
        path_dir['pc_overflow_result']['stdout']=str(state.posix.dumps(1))
        path_dir['pc_overflow_result']['chain']=print_paths
        
        if 'argv'in state.globals:
            argv=state.globals['argv']
            argv_ret=[]
            for x in argv:
                # print(state.solver.eval(x,cast_to=bytes))
                argv_ret.append( str(state.solver.eval(x,cast_to=bytes)) )
            path_dir['pc_overflow_result']['argv']=argv_ret

        fp=open("tmp.json","a")
        json_str = json.dumps(path_dir)
        fp.write(json_str+"\n")
        fp.close()


def print_bp_overflow_msg(state,byte_s):
    hists=state.history.bbl_addrs.hardcopy
    paths,print_paths=ct.deal_history(state,hists)
    bp_overflow_maps=state.globals['bp_overflow_maps']
    limit=state.globals['limit']
    if ct.cmp_path(paths,bp_overflow_maps,limit):

        path_dir={'bp_overflow_result':{}}
        path_dir['bp_overflow_result']['over_num']=hex(byte_s)
        path_dir['bp_overflow_result']['stdin']=str(state.posix.dumps(0))
        path_dir['bp_overflow_result']['stdout']=str(state.posix.dumps(1))
        path_dir['bp_overflow_result']['chain']=print_paths
 
        if 'argv'in state.globals:
            argv=state.globals['argv']
            argv_ret=[]
            for x in argv:
                argv_ret.append( str(state.solver.eval(x,cast_to=bytes)) )
            path_dir['bp_overflow_result']['argv']=argv_ret

        fp=open("tmp.json","a")
        json_str = json.dumps(path_dir)
        fp.write(json_str+"\n")
        fp.close()

def check_end(state):
    if state.addr==0:
        return
    insns=state.project.factory.block(state.addr).capstone.insns
    if len(insns)>=2:
        flag=0
        #check for : leave; ret;
        for ins in insns:
            if ins.insn.mnemonic=="leave":
                flag+=1
            if ins.insn.mnemonic=="ret":
                flag+=1

        if flag==2:
            rsp=state.regs.rsp
            rbp=state.regs.rbp
            byte_s=state.arch.bytes
            stack_rbp=state.memory.load(rbp,endness=angr.archinfo.Endness.LE)
            stack_ret=state.memory.load(rbp+byte_s,endness=angr.archinfo.Endness.LE)
            pre_target=state.callstack.ret_addr
            pre_rbp=state.globals['rbp_list'][hex(pre_target)]

            if stack_ret.symbolic:
                num=check_symbolic_bits(state,stack_ret)
                print_pc_overflow_msg(state,num//byte_s)
                
                state.memory.store(rbp,pre_rbp,endness=angr.archinfo.Endness.LE)
                state.memory.store(rbp+byte_s, state.solver.BVV(pre_target, 64),endness=angr.archinfo.Endness.LE)
                return
                
            if stack_rbp.symbolic:
                num=check_symbolic_bits(state,stack_rbp)
                print_bp_overflow_msg(state,num//byte_s)
                state.memory.store(rbp,pre_rbp,endness=angr.archinfo.Endness.LE)

def check_head(state):    
    insns=state.project.factory.block(state.addr).capstone.insns
    if len(insns)>=2:
        #check for : push rbp; mov rsp,rbp; 
        ins0=insns[0].insn
        ins1=insns[1].insn
        if len(ins0.operands)==1 and len(ins1.operands)==2:
            ins0_name=ins0.mnemonic#push 
            ins0_op0=ins0.reg_name(ins0.operands[0].reg)#rbp
            ins1_name=ins1.mnemonic#mov 
            ins1_op0=ins1.reg_name(ins1.operands[0].reg)#rsp
            ins1_op1=ins1.reg_name(ins1.operands[1].reg)#rbp

            if ins0_name=="push" and ins0_op0=="rbp" and ins1_name=="mov" and ins1_op0=="rbp" and ins1_op1=="rsp":
                pre_target=state.callstack.ret_addr
                state.globals['rbp_list'][hex(pre_target)]=state.regs.rbp



def Check_StackOverflow(binary,args=None,start_addr=None,limit=None):
    argv=ct.create_argv(binary,args)
    extras = {so.REVERSE_MEMORY_NAME_MAP, so.TRACK_ACTION_HISTORY,so.ZERO_FILL_UNCONSTRAINED_MEMORY}
    p = angr.Project(binary,auto_load_libs=False)

    if start_addr:
        state=p.factory.blank_state(addr=start_addr,add_options=extras)
    else:
        state=p.factory.full_init_state(args=argv,add_options=extras)#,stdin=str_in
        # state=p.factory.entry_state(args=argv,add_options=extras)
    if limit:
        state.globals['limit']=limit
    else:
        state.globals['limit']=3
    
    state.globals['bp_overflow_maps'] = []
    state.globals['pc_overflow_maps']= []
    state.globals['filename']=binary
    state.globals['rbp_list']={}
    
    if len(argv)>=2:
        state.globals['argv']=[]
        for i in range(1,len(argv)):
            state.globals['argv'].append(argv[i])

    simgr = p.factory.simulation_manager(state,save_unconstrained=True)#veritesting=True
    simgr.use_technique(angr.exploration_techniques.Spiller())

    while simgr.active:
        for act in simgr.active:
            check_head(act)
            check_end(act)
        if simgr.unconstrained:
            tmp=simgr.unconstrained[-1]
            print("unconstrained:",tmp)
            print(tmp.regs.pc)
            print(tmp.regs.sp)
            print(tmp.regs.bp,"\n")
        simgr.step()

if __name__ == '__main__':    
    filename="./test1"
    Check_StackOverflow(filename)
