import os
import sys
import subprocess
import nuke
import nukescripts
import json
import traceback
import socket
import ipaddress

try:
    from typing import Any, Dict, List, Optional, Tuple, Union
except ImportError:
    pass

CUSTOM_DEADLINE_API_LOCATION = "" #path/to/your/api/python-folder -> custoom api folder
DEADLINE_WEBSERVICE_URL = "" #URL for your web service -> https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/standalone-python.html
DEADLINE_WEBSERVICE_PORT = "" #port

CopyCatDialog = None 
machines = []

def get_ip(hostname):
    try:
        ip_address = socket.gethostbyname(hostname)
        return str(ip_address)
    except Exception as e:
        print(f"Error getting local IP address: {e}")
        return None

#IPv6 is set here but for now plugin works on IPv4
def get_ipv6(hostname):
    try:      
        ipv6 = socket.getaddrinfo(hostname, None, socket.AF_INET6)
        
        for entry in ipv6:
            if entry[4][0] != "::1":  # Exclude loopback address (::1)
                return str(entry[4][0])
        return "::1"
    except Exception as e:
        print(f"Error getting local IPv6 address: {e}")
        return None

class CopyCatStandaloneDialog(nukescripts.PythonPanel):

    def __init__(self, nodes):
        super().__init__()       
        width = 580
        height = 500        
                
        self.setMinimumSize(width, height)
        self.CopyCatNodes = nodes
        self._jobInfo = {}
        self._pluginInfo = {}
        self._nukeVersionMajor = getNukeVersion()[0]
        self._nukeVersionMinor = getNukeVersion()[1]

        self.getSubbmitionInfo()
        
        self.maximumPriority = int(self.submissionInfo.get("MaxPriority", 100))        
        self.initUI()

    def initUI(self):
        global machines
        # Separator
        self.separator1 = nuke.Text_Knob("Deadline_Separator1", "")
        self.addKnob(self.separator1)

        ## JOB ##
        root_scene_name = self.getSceneRootName()
        self.jobName= nuke.String_Knob("Deadline_JobName", "Job Name")
        self.addKnob(self.jobName)
        self.jobName.setTooltip("The name of your job. This is optional, and if left blank, it will default to 'CopyCat - root name of scene or untittled'.")
        self.jobName.setValue(root_scene_name)
        # Comment
        self.comment = nuke.String_Knob("Deadline_Comment", "Comment")
        self.addKnob(self.comment)
        self.comment.setTooltip("A simple description of your job. This is optional and can be left blank.")
        self.comment.setValue("")
        
        # Department
        self.department = nuke.String_Knob("Deadline_Department", "Department")
        self.addKnob(self.department)
        self.department.setTooltip("The department you belong to. This is optional and can be left blank.")
        self.department.setValue("")
        
        # Separator
        self.separator2 = nuke.Text_Knob("Deadline_Separator2", "")
        self.addKnob(self.separator2)

        # Pool
        pools = self.submissionInfo['Pools']
        self.pool = nuke.Enumeration_Knob("Deadline_Pool", "Pool", pools)
        self.addKnob(self.pool)
        self.pool.setTooltip("The pool that your job will be submitted to.")
        self.pool.setValue("copycat")

        self.secondarypool = nuke.Enumeration_Knob("Secondary_Deadline_Pool", "Secondary Pool", pools)
        self.addKnob(self.secondarypool)
        self.secondarypool.setTooltip("The pool that your job will be submitted to.")
        self.secondarypool.setValue("none")

        # Groups
        groups = self.submissionInfo['Groups']
        self.group = nuke.Enumeration_Knob("Deadline_Group", "Group", groups)
        self.addKnob(self.group)
        self.group.setTooltip("The group that your job will be submitted to.")
        self.group.setValue("copycat")

        # Separator
        self.separator3 = nuke.Text_Knob("Deadline_Separator3", "")
        self.addKnob(self.separator3)

         ## CopyCat to train ##        
        self.nodeTorender = nuke.Enumeration_Knob("CopyCat_Node", "CopyCat Node to render", self.CopyCatNodes)
        self.addKnob(self.nodeTorender)
        self.nodeTorender.setTooltip("CopyCat Node to render")

        ## CopyCat main machine ##
        machines = self.getCopyCatMachines() #type: list
        self.mainMachine = nuke.Enumeration_Knob("Main_CopyCat_Machine", "Main Machine", machines)
        self.addKnob(self.mainMachine)
        self.mainMachine.setTooltip("Main CopyCat machine")

        self.manMachineIp= nuke.String_Knob("Copy_Cat_mainMachine_ip", "IP")
        self.addKnob(self.manMachineIp)
        ipv4 = get_ip(self.mainMachine.value())
        if not ipv4:
            print("Subbmiter did not get IP, please set it on your own.")
            ipv4 = ""
        self.manMachineIp.setValue(str(ipv4))
        self.manMachineIp.setTooltip("IP of Main CopyCat machine")

        self.useIpV6 = nuke.Boolean_Knob("Use_IPv6", "Use IPv6")
        self.useIpV6.clearFlag(nuke.STARTLINE)
        self.addKnob(self.useIpV6)
        self.setTooltip("Use IPv6 instead IPv4")

        self.port = nuke.Int_Knob("CopyCat port", "Port")        
        self.addKnob(self.port)
        self.port.setTooltip("CopyCat port for communication with main machine")
        self.port.setValue(3000) #default by Foundry

        self.syncInterval = nuke.Int_Knob("CopyCat Sync interval", "SyncInterval")
        self.addKnob(self.syncInterval)
        self.syncInterval.setTooltip("Sync he interval at which gradients are shared between processes. By default, synchronization happens every 1 step. \
                                     You can increase this value for better network latency")
        self.syncInterval.setValue(1)

        ## machines for traning ##
        self.worldsize = nuke.Int_Knob("CopyCat_world_size", "World size")        
        self.addKnob(self.worldsize)
        self.worldsize.setTooltip("Use the World Size to specify copyCat World Size environment variable")
        self.worldsize.setEnabled(False)
        self.worldsize.setValue(0)
        if machines:
            self.worldsize.setValue(len(machines))

        self.machineList = nuke.String_Knob("CopyCat_Machines", "Machines for job")
        self.addKnob(self.machineList)
        self.port.clearFlag(nuke.STARTLINE)
        self.machineList.setTooltip("List of machines that will be used for job")
        self.machineList.setValue("")
        self.getMachinesInOrder()
        self.machineListButton = nuke.PyScript_Knob("CopyCat_Machines_Browse", "Browse")
        self.addKnob(self.machineListButton)    

        # Separator
        self.separator5 = nuke.Text_Knob("Deadline_Separator5", "")
        self.addKnob(self.separator5)   

        # Priority       
        self.priority = nuke.Int_Knob("Deadline_Priority", "Priority")
        self.addKnob(self.priority)
        self.priority.setTooltip("A job can have a numeric priority ranging from 0 to " + str(self.maximumPriority) + ", where 0 is the lowest priority.")
        self.priority.setValue(50)

        self.separator6 = nuke.Text_Knob("Deadline_Separator6", "")
        self.addKnob(self.separator6)  

        # Use GPU
        self.useGpu = nuke.Boolean_Knob("Deadline_UseGpu", "Use The GPU For CopyCat")
        self.addKnob(self.useGpu)
        self.useGpu.setTooltip("If Nuke should also use the GPU for CopyCat.")
        self.useGpu.setEnabled(True)
        self.useGpu.setValue(True) 

        # Choose GPU
        self.chooseGpu = nuke.Int_Knob("Deadline_ChooseGpu", "GPU Override")
        self.addKnob(self.chooseGpu)
        self.chooseGpu.setTooltip("The GPU to use for CopyCat process.")
        self.chooseGpu.setValue(0)
        self.chooseGpu.setEnabled(self.useGpu.value()) 
        
        self.useSpecificGpu  = nuke.Boolean_Knob("Deadline_UseSpecificGpu", "Use Specific GPU Override")
        self.addKnob(self.useSpecificGpu)
        self.useSpecificGpu.setTooltip("If enabled the specified GPU Index will be used for all Workers. Otherwise each Worker will use it's overrides.")
        self.useSpecificGpu.setValue(False)
        self.useSpecificGpu.setEnabled(True)   

        # Submit Scene
        self.submitScene = nuke.Boolean_Knob("Deadline_SubmitScene", "Submit Nuke Script File With Job")
        self.submitScene.setFlag(nuke.STARTLINE)
        self.addKnob(self.submitScene)
        self.submitScene.setTooltip("If this option is enabled, the Nuke script file will be submitted with the job, and then copied locally to the Worker machine during rendering.")
        self.submitScene.setValue(True)   
    
    def knobChanged(self, knob):
        if knob == self.machineListButton:
            args = ["-selectmachinelist"]
            output = CallDeadlineCommand(args, False)          
            output = output.replace( "\r", "" ).replace( "\n", "" )
            if output != "Action was cancelled by user":
                self.machineList.setValue(output)
        
        if knob == self.useGpu:
            self.useSpecificGpu.setEnabled(self.useGpu.value())

        if knob == self.useSpecificGpu:
            if self.useSpecificGpu:
                self.chooseGpu.setEnabled(self.useSpecificGpu.value())   

        if knob == self.useIpV6:            
            ipv6 = get_ipv6(self.mainMachine.value())
            if not ipv6:
                ipv6 = ""
            self.manMachineIp.setValue(ipv6)
        
        if knob == self.mainMachine:
            self.getMachinesInOrder()
        
        if knob == self.machineList:
            self.setWorldSize()

    def getMachinesInOrder(self):
        global machines
        if machines:                   
            main_machine = self.mainMachine.value()            
            if main_machine in machines:
                machines.remove(main_machine)
                machines.insert(0, main_machine)
            result = ','.join(str(machine) for machine in machines)
            self.machineList.setValue(result)             

    def setWorldSize(self):
        tmplist = self.machineList.value().split(",")
        tmplist = [machine for machine in tmplist if machine.strip() != ""]
        self.worldsize.setValue(len(tmplist))        

    def getJobInfoDict(self):
        global machines
        self._jobInfo['Plugin'] = "CopyCat"
        self._jobInfo['Name'] = self.jobName.value()
        self._jobInfo['Comment'] = self.comment.value()
        self._jobInfo['Department'] = self.department.value()
        self._jobInfo['Pool'] = self.pool.value()
        self._jobInfo['SecondaryPool'] = self.secondarypool.value()
        self._jobInfo['Group'] = self.group.value()
        self._jobInfo['Frames'] = f"1-{str(len(machines))}"
        # Output       
        output = self.getOutputDirFromNode()
        if output == "":
            nuke.message("No output directory in CopyCat node provided!\nCanceling submission...")
            return None
        self._jobInfo['OutputDirectory'] = output
        self._jobInfo['Priority'] = self.priority.value()
    
    def getPluginInfo(self):                        
        self._pluginInfo["BatchMode"] = False            
        self._pluginInfo["BatchModeIsMovie"] = False
        self._pluginInfo["ContinueOnError"] = False
        self._pluginInfo["EnforceRenderOrder"] =  False        
        self._pluginInfo["UseGpu"] = bool(self.useGpu.value())  
        self._pluginInfo["UseSpecificGpu"] = self.useSpecificGpu.value()         
        self._pluginInfo["GpuOverride"] = 0 if not self.useSpecificGpu.value() else int(self.chooseGpu.value())
        self._pluginInfo['SceneFile'] = nuke.Root().name()        
        self._pluginInfo["Version"] = f"{self._nukeVersionMajor}.{self._nukeVersionMinor}"   
        #main machine
        self._pluginInfo['MainMachine'] = self.mainMachine.value()
        self._pluginInfo['Port'] = self.port.value()
        #rendering machines        
        self._pluginInfo['TrainingSlaves'] = self.machineList.value() 
        self._pluginInfo['WorldSize'] = self.worldsize.value()
        self._pluginInfo['CopyCatNode'] = self.nodeTorender.value()
        self._pluginInfo['SyncInterval'] = int(self.syncInterval.value())
        self._pluginInfo['UseIPv6'] = self.useIpV6.value()
        self._pluginInfo['MainMachineIP'] = self.manMachineIp.value()

        return self._pluginInfo

    def getOutputDirFromNode(self):
        node_name = self.nodeTorender.value()
        node = nuke.toNode(node_name)
        knob_name = "dataDirectory"

        outputDir = ""
        if knob_name in node.knobs():
            outputDir = node.knobs()[knob_name].value()

        return outputDir
        
    def getSceneRootName(self):
        root_node = nuke.root()
        scene_name = root_node.name()

        if scene_name == "Root":
            return "untittled"
        
        return os.path.basename(scene_name)

    def getSubbmitionInfo(self):
        print("Grabbing submitter info...")
        self.submissionInfo = {}
        args = ["-GetSubmissionInfo", "Pools", "Groups", "MaxPriority", "UserHomeDir", "RepoDir:custom/submission/Nuke/Main", "RepoDir:submission/Integration/Main"]        
        output = getJSONResponseFromDeadline(args)# type: Dict
        self.submissionInfo = output

    def getCopyCatMachines(self):
        machines = {}
        args = ["-GetSlaveNamesInGroup", "copycat"]
        machines = getJSONResponseFromDeadline(args)         
        return machines 

    def ShowDialog(self):
        # type: () -> bool        
        return nukescripts.PythonPanel.showModalDialog(self)


def getNukeVersion():
    """
    Grabs the current Nuke version as a tuple of ints.
    :return: Nuke version as a tuple of ints
    """
    # The environment variables themselves are integers. But since we can't test Nuke 6 to ensure they exist,
    # we have to use their `GlobalsEnvironment`, not a dict, get method which only accepts strings as defaults.
    return (
        int(nuke.env.get('NukeVersionMajor', '6')),
        int(nuke.env.get('NukeVersionMinor', '0')),
        int(nuke.env.get('NukeVersionRelease', '0')),
    )

def getJSONResponseFromDeadline(arguments: list) -> Any:        
    result = {}
    json_arg = ["-prettyJSON"]
    cmd  = json_arg + arguments
    try:
        result = json.loads(CallDeadlineCommand(cmd)) # type: Dict
    except:
        print("Unable to get submitter info from Deadline:\n\n" + traceback.format_exc())
        raise

    if result[ "ok" ]:
        result = result[ "result" ] 
    else:
        print("DeadlineCommand returned a bad result and was unable to grab the submitter info.\n\n" + result[ "result" ])
        raise Exception(result[ "result" ])

    return result #type: Optional[dict | list]

def GetMachineListFromDeadline():
    # type: () -> None
    global CopyCatDialog
    
    if CopyCatDialog is not None:
        args = ["-selectmachinelist", CopyCatDialog.machineList.value()]
        output = CallDeadlineCommand(args, False)
        output = output.replace("\r", "").replace("\n", "")
        if output != "Action was cancelled by user":
            print(output)

def getCopyCatNodes() -> List:    
    nodes = nuke.selectedNodes() 
    copycatNodes = [node.name() for node in nodes if node.Class() == "CopyCat"]
    return copycatNodes #type list[str]   

def SubmitToDeadline():    
    # Get the root node.
    root = nuke.Root() # type: Any
    studio = False # type: bool
    noRoot = False # type: bool
    if 'studio' in nuke.env.keys() and nuke.env[ 'studio' ]:
        studio = True
    # If the Nuke script hasn't been saved, its name will be 'Root' instead of the file name.
    if root.name() == "Root":
        noRoot = True
        if not studio:
            nuke.message("The Nuke script must be saved before it can be submitted to Deadline.")
            return
        
    # If the Nuke script has been modified, then save it.
    if root.modified() and not noRoot:
        if root.name() != "Root":
            nuke.scriptSave(root.name())

    nukeVersion = getNukeVersion() # type: Tuple[int, int, int]    
    if nukeVersion < (14, 1, ): #CopyCat is used only in 14.1 +
        nuke.message("Your version is too low!\nPlease Use Nuke 14.1 or higer vresion")
        return

    nodes = getCopyCatNodes()
    if len(nodes) == 0:        
        nuke.message("Please select a CopyCat node")
        return    
    
    CopyCatDialog = CopyCatStandaloneDialog(nodes)    
    global machines

    jobInfo = {}
    pluginInfo = {}
    firstMachine = machines[0].strip().lower()

    success = False # type: bool
    while not success:
        success = CopyCatDialog.ShowDialog()
        if not success:            
            return
        
        if CopyCatDialog.mainMachine.value().strip().lower() != firstMachine:   
            reordermachines = nuke.ask("Your MainMachine is not first machine in list, if you proceed machines will be reordered.")
            if reordermachines:
                CopyCatDialog.getMachinesInOrder()
            else:
                return

        if CopyCatDialog.manMachineIp.value() == "":
            nuke.message("Please provide main machine IP")
            return

        #Check IP format
        if CopyCatDialog.useIpV6.value():
            ip_obj = ipaddress.ip_address(CopyCatDialog.manMachineIp.value())
            if not isinstance(ip_obj, ipaddress.IPv6Address):
                nuke.message("Please provide main machine IPv6 adderss")
                return
        else:
            ip_obj = ipaddress.ip_address(CopyCatDialog.manMachineIp.value())
            if not isinstance(ip_obj, ipaddress.IPv4Address):
                nuke.message("Please provide main machine IPv4 address")
                return

        #Job and plugin info dicts
        jobInfo = CopyCatDialog.getJobInfoDict()
        if not jobInfo:
            nuke.message("JobInfo dict for CopyCat are not generated. The submission has been canceled.")    
            return        
        
        pluginInfo = CopyCatDialog.getPluginInfo()
        if not pluginInfo:
            nuke.message("Plugin dict for CopyCat are not generated. The submission has been canceled.")
            return
        

        SubmitJob(jobInfo, pluginInfo)

def connect_to_api():
    if os.path.isdir(CUSTOM_DEADLINE_API_LOCATION):
        deadline_api = CUSTOM_DEADLINE_API_LOCATION
    else: 
        deadline_api = os.path.join(os.environ['DEADLINE_REPOSITORY'], "api", "python") #if not it will use DEADLINE_REPOSITORY env var and pic api from there
    deadline_web_url = DEADLINE_WEBSERVICE_URL
    deadline_port = DEADLINE_WEBSERVICE_PORT

    #append api to sys
    sys.path.append(deadline_api)
    deadline_connect = None
    try:
        import Deadline.DeadlineConnect as Connect
        deadline_connect = Connect.DeadlineCon(deadline_web_url, deadline_port)
    except Exception as e:
        print(f"ERROR:{e}")  
    
    return deadline_connect

def SubmitJob(jobInfo, pluginInfo):
    api_connection = connect_to_api()
    AuxFile = nuke.root().name() # Auxiliary 
    # For job Auxiliary files, because we use web service, the Web Service machine executes deadline submit 
    # Command instead your PC. So if you are set it up on Linux machine you will need to modify also paths
    # Here is just example how it can be done
    # if AuxFile.startswith("Y:"):
    #     AuxFile = AuxFile.split(':')[1]  # Remove the drive letter and colon
    # AuxFile = AuxFile.replace('\\', '/')  # Replace backslashes with forward slashes
    # AuxFile = f"/mnt/y{AuxFile}"  # Prep linux base path, Y: is mapped to /mnt/y

    #subbmit over web api
    if api_connection:
        api_connection.Jobs.SubmitJob(jobInfo, pluginInfo, AuxFile)
    else:
        print("Connection with API is not established")        

def CallDeadlineCommand(arguments, hideWindow=True):
    # type: (List[str], bool) -> str
    deadlineCommand = GetDeadlineCommand() # type: str
    
    startupinfo = None # type: ignore # this is only a windows option
    if hideWindow and os.name == 'nt':
        # Python 2.6 has subprocess.STARTF_USESHOWWINDOW, and Python 2.7 has subprocess._subprocess.STARTF_USESHOWWINDOW, so check for both.
        if hasattr(subprocess, '_subprocess') and hasattr(subprocess._subprocess, 'STARTF_USESHOWWINDOW'): # type: ignore # this is only a windows option
            startupinfo = subprocess.STARTUPINFO() # type: ignore # this is only a windows option
            startupinfo.dwFlags |= subprocess._subprocess.STARTF_USESHOWWINDOW # type: ignore # this is only a windows option
        elif hasattr(subprocess, 'STARTF_USESHOWWINDOW'):
            startupinfo = subprocess.STARTUPINFO() # type: ignore # this is only a windows option
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW # type: ignore # this is only a windows option
    
    environment = {} # type: Dict[str, str]
    for key in os.environ.keys():
        environment[key] = str(os.environ[key])
        
    # Need to set the PATH, cuz windows seems to load DLLs from the PATH earlier that cwd....
    if os.name == 'nt':
        deadlineCommandDir = os.path.dirname(deadlineCommand)
        if not deadlineCommandDir == "" :
            environment['PATH'] = deadlineCommandDir + os.pathsep + os.environ['PATH']
    
    arguments.insert(0, deadlineCommand)
    output = "" # type: Union[bytes, str]
    
    # Specifying PIPE for all handles to workaround a Python bug on Windows. The unused handles are then closed immediatley afterwards.
    proc = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, env=environment)
    output, errors = proc.communicate()

    if sys.version_info[0] > 2 and type(output) is bytes:
        output = output.decode()
    return output # type: ignore

def GetDeadlineCommand():
    # type: () -> str
    deadlineBin = "" # type: str
    try:
        deadlineBin = os.environ['DEADLINE_PATH']
    except KeyError:
        #if the error is a key error it means that DEADLINE_PATH is not set. however Deadline command may be in the PATH or on OSX it could be in the file /Users/Shared/Thinkbox/DEADLINE_PATH
        pass
        
    # On OSX, we look for the DEADLINE_PATH file if the environment variable does not exist.
    if deadlineBin == "" and  os.path.exists("/Users/Shared/Thinkbox/DEADLINE_PATH"):
        with open("/Users/Shared/Thinkbox/DEADLINE_PATH") as f:
            deadlineBin = f.read().strip()

    deadlineCommand = os.path.join(deadlineBin, "deadlinecommand") # type: str
    
    return deadlineCommand