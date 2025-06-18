#!/usr/bin/env python3

from __future__ import absolute_import
import re
import os
import socket

from System import Environment
from System.Diagnostics import ProcessStartInfo, Process, ProcessPriorityClass
from System.IO import Path, Directory, File

from Deadline.Plugins import DeadlinePlugin, PluginType
from Deadline.Scripting import SystemUtils, PathUtils, RepositoryUtils

from FranticX.Processes import ManagedProcess
from six.moves import range

######################################################################
## This is the function that Deadline calls to get an instance of the
## main DeadlinePlugin class.
######################################################################
def GetDeadlinePlugin():
    return CopyCatPlugin()

def CleanupDeadlinePlugin( deadlinePlugin ):
    deadlinePlugin.Cleanup()

def get_local_ipv4():
    try:
        # Open a dummy socket to a public IPv4 address (doesn't send any data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except Exception as e:
        print(f"Error getting local IP address: {e}")
        return None

#IPv6 is set here but for now plugin works on IPv4
def get_local_ipv6():
    try:
        hostname = socket.gethostname()
        
        ipv6 = socket.getaddrinfo(hostname, None, socket.AF_INET6)
        
        for entry in ipv6:
            if entry[4][0] != "::1":  # Exclude loopback address (::1)
                return entry[4][0]
        return "::1"
    except Exception as e:
        print(f"Error getting local IPv6 address: {e}")
        return None


######################################################################
## This is the main DeadlinePlugin class for the Nuke plugin.
######################################################################
class CopyCatPlugin (DeadlinePlugin):
    Version = -1.0
    BatchMode = False
    Process = None
    ProcessName = "CopyCat Nuke"
    
    ## Utility functions
    def WritePython( self, statement ):
        self.FlushMonitoredManagedProcessStdout( self.ProcessName )
        self.WriteStdinToMonitoredManagedProcess( self.ProcessName, statement )
        self.WaitForProcess()
    
    def WaitForProcess( self ):
        self.FlushMonitoredManagedProcessStdout( self.ProcessName )
        self.WriteStdinToMonitoredManagedProcess( self.ProcessName, self.Process.ReadyForInputCommand() )
        while not self.Process.IsReadyForInput():
            self.VerifyMonitoredManagedProcess( self.ProcessName )
            self.FlushMonitoredManagedProcessStdout( self.ProcessName )
            
            blockingDialogMessage = self.CheckForMonitoredManagedProcessPopups( self.ProcessName )
            if( blockingDialogMessage != "" ):
                self.FailRender( blockingDialogMessage )
            
            if self.IsCanceled():
                self.FailRender( "Received cancel task command" )
            
            SystemUtils.Sleep( 100 )
        
        self.Process.ResetReadyForInput()
        
    def scrubLibPath( self, envVar ):
        ldPaths = Environment.GetEnvironmentVariable(envVar)
        if ldPaths:
            ldPaths = ldPaths.split(":")
            newLDPaths = []
            for ldPath in ldPaths:
                if not re.search("Deadline",ldPath):
                    newLDPaths.append(ldPath)
            
            if len(newLDPaths):
                newLDPaths = ":".join(newLDPaths)
            else:
                newLDPaths = ""
            
            self.SetProcessEnvironmentVariable(envVar,newLDPaths)
            del ldPaths
            del newLDPaths
        
    def scrubLibPaths( self ):
        """This solves a library / plugin linking issue with Nuke that occurs
        when Nuke sees the IlmImf library included with Deadline.  It appears that library
        conflicts with the exrWriter and causes it to error out.  This solution
        removes the Deadline library paths from the LD and DYLD library paths
        before Deadline launches Nuke, so Nuke never sees that library.  It seems like
        this fixes the problem. Thanks to Matt Griffith for figuring this one out!"""
        
        self.LogInfo("Scrubbing the LD and DYLD LIBRARY paths")
        
        self.scrubLibPath("LD_LIBRARY_PATH")
        self.scrubLibPath("DYLD_LIBRARY_PATH")
        self.scrubLibPath("DYLD_FALLBACK_LIBRARY_PATH")
        self.scrubLibPath("DYLD_FRAMEWORK_PATH")
        self.scrubLibPath("DYLD_FALLBACK_FRAMEWORK_PATH")
    
    def prepForOFX(self):
        """This solves an issue where Nuke can fail to create the ofxplugincache,
        which causes any script submited to Deadline that uses an OFX plugin to fail.
        Thanks to Matt Griffith for figuring this one out!"""
        
        self.LogInfo("Prepping OFX cache")
        nukeTempPath = ""
        
        # temp path for Nuke
        if SystemUtils.IsRunningOnWindows():
            # on windows, nuke temp path is [Temp]\nuke
            nukeTempPath = Path.Combine( Path.GetTempPath(), "nuke" )
        else:
            # on *nix, nuke temp path is "/var/tmp/nuke-u" + 'id -u'
            id = PathUtils.GetApplicationPath( "id" )
            if len(id) == 0:
                self.LogWarning( "Could not get path for 'id' process, skipping OFX cache prep" )
                return
            
            startInfo = ProcessStartInfo( id, "-u" )
            startInfo.RedirectStandardOutput = True
            startInfo.UseShellExecute = False
            
            idProcess = Process()
            idProcess.StartInfo = startInfo
            idProcess.Start()
            idProcess.WaitForExit()
            
            userId = idProcess.StandardOutput.ReadLine()
            
            idProcess.StandardOutput.Close()
            idProcess.StandardOutput.Dispose()
            idProcess.Close()
            idProcess.Dispose()
            
            if len(userId) == 0:
                self.LogWarning( "Failed to get user id, skipping OFX cache prep" )
                return
            
            nukeTempPath = "/var/tmp/nuke-u" + userId
        
        self.LogInfo( "Checking Nuke temp path: " + nukeTempPath)
        if Directory.Exists(nukeTempPath):
            self.LogInfo( "Path already exists" )
        else:
            self.LogInfo( "Path does not exist, creating it..." )
            Directory.CreateDirectory(nukeTempPath) #creating this level of the nuke temp directory seems to be enough to let the ofxplugincache get created -mg
            
            if Directory.Exists(nukeTempPath):
                self.LogInfo( "Path now exists" )
            else:
                self.LogWarning( "Unable to create path, skipping OFX cache prep" )
                return
        
        self.LogInfo("OFX cache prepped")

    def __init__( self ):
        super().__init__()
        self.StartJobCallback += self.NukeSetup
        self.RenderTasksCallback += self.RenderCopyCat
        self.EndJobCallback += self.EndJob
        self.InitializeProcessCallback += self.InitializeProcess
        
    
    def Cleanup(self):
        del self.StartJobCallback
        del self.RenderTasksCallback
        del self.EndJobCallback
        del self.InitializeProcessCallback
        del self.IsSingleFramesOnlyCallback
        
        if self.Process:
            self.Process.Cleanup()
            del self.Process
    
    ## Called by Deadline to initialize the process.
    def InitializeProcess( self ):
        # Set the plugin specific settings.
        self.SingleFramesOnly = False
        self.PluginType = PluginType.Advanced
    
    def NukeSetup( self ):
        # This fixes a library conflict issue on non-Windows systems.
        if not SystemUtils.IsRunningOnWindows():
            self.scrubLibPaths()
        
        if self.GetBooleanConfigEntryWithDefault( "PrepForOFX", True ):
            # Ensure that OFX plugins will work
            try:
                self.prepForOFX()
            except:
                self.LogWarning( "Prepping of OFX cache failed" )
        
        self.Version = float( self.GetPluginInfoEntry( "Version" ) )

        if self.Version >= 14.1:
            self.SetupCopyCatEnv()
        else:
            self.FailRender(f"Nuke version {str(self.Version)} is currently not supported for CopyCat." )
        
        # Since we now support minor versions, we should default to the *.0 version if the *.X version they're using isn't supported yet.
        versionNotSupported = "this version is not supported yet"
        nukeExeList = self.GetConfigEntryWithDefault( "RenderExecutable" + str(self.Version).replace( ".", "_" ), versionNotSupported )
        if nukeExeList == versionNotSupported:
            oldVersion = self.Version
            self.Version = float(int(self.Version))
            
            nukeExeList = self.GetConfigEntryWithDefault( "RenderExecutable" + str(self.Version).replace( ".", "_" ), versionNotSupported )
            if nukeExeList == versionNotSupported:
                self.FailRender( "Nuke major version " + str(int(self.Version)) + " is currently not supported." )
            else:
                self.LogWarning( "Nuke minor version " + str(oldVersion) + " is currently not supported, so version " + str(self.Version) + " will be used instead." )

    def RenderCopyCat( self ):        
        self.Process = CopyCatProcess( self, self.Version )        
        self.RunManagedProcess( self.Process )
    
    def EndJob( self ):        
        self.FlushMonitoredManagedProcessStdoutNoHandling( self.ProcessName )
        self.WriteStdinToMonitoredManagedProcess( self.ProcessName, "quit()" )
        self.FlushMonitoredManagedProcessStdoutNoHandling( self.ProcessName )
        self.WaitForMonitoredManagedProcessToExit( self.ProcessName, 5000 )
        self.ShutdownMonitoredManagedProcess( self.ProcessName )

    def SetupCopyCatEnv(self):
        self.LogInfo("Attempting to set COPYCAT Environment...")
        mainmachine = self.GetPluginInfoEntry("MainMachine").lower()
        
        mainMachineIp = self.GetPluginInfoEntry("MainMachineIP")
        useIpv6 = self.GetBooleanPluginInfoEntryWithDefault("UseIPv6", False) 
        worldSize = self.GetIntegerPluginInfoEntry("WorldSize")
        port = self.GetIntegerPluginInfoEntryWithDefault("Port", 3000)
        othermachines = self.GetPluginInfoEntry("TrainingSlaves") 
        syncInterval = self.GetIntegerPluginInfoEntryWithDefault("SyncInterval", 1) 
        rank = 0 # Main machine rank
        othermachineslist = othermachines.split(",")  

        # Check world size before render, if is not set coreectly (for example you are added new machine via monitor) 
        # this will correct it and run process with proper world size
        if (worldSize != len(othermachineslist)):
            worldSize = len(othermachineslist)

        ipAddress = get_local_ipv4() if not useIpv6 else get_local_ipv6()
        thisMachine = self.GetSlaveName().lower()    
        print(f"Current Machine IP: {ipAddress}")  
        print(f"Current Machine Name: {thisMachine}")   
        # main machine is rank 0 so if not main machine give it different rank
        if thisMachine != mainmachine:
            print("this is not main machine")
            print(f"othermachineslist: {othermachineslist}")
            for index, machineName in enumerate(othermachineslist):
                if machineName.strip().lower() == thisMachine:   
                    print("setting rank for this machine")                 
                    rank = index       

        #when this machine is mainmachine check it IP
        if thisMachine == mainmachine and ipAddress != mainMachineIp:
            self.FailRender("Your Main Machine IP is incorrect! Please check main machine IP!")
    
        self.SetProcessEnvironmentVariable("COPYCAT_MAIN_ADDR", str(mainMachineIp))  
        self.SetProcessEnvironmentVariable("COPYCAT_RANK", str(rank))
        self.SetProcessEnvironmentVariable("COPYCAT_LOCAL_ADDR", str(ipAddress))
        self.SetProcessEnvironmentVariable("COPYCAT_MAIN_PORT", str(port))
        self.SetProcessEnvironmentVariable("COPYCAT_WORLD_SIZE", str(worldSize))
        self.SetProcessEnvironmentVariable("COPYCAT_SYNC_INTERVAL", str(syncInterval))        
        self.LogInfo(f"CopyCat Environment is set...")

class CopyCatProcess (ManagedProcess):
    deadlinePlugin = None
    
    TempSceneFilename = ""
    Version = -1.0
    BatchMode = False
    ReadyForInput = False

    #Utility functions
    def pathMappingWithFilePermissionFix( self, inFileName, outFileName, stringsToReplace, newStrings ):
        RepositoryUtils.CheckPathMappingInFileAndReplace( inFileName, outFileName, stringsToReplace, newStrings )
        if SystemUtils.IsRunningOnLinux() or SystemUtils.IsRunningOnMac():
            os.chmod( outFileName, os.stat( inFileName ).st_mode )
            
    def __init__( self, deadlinePlugin, version):
        super().__init__()
        self.deadlinePlugin = deadlinePlugin
        
        self.Version = version
        
        self.InitializeProcessCallback += self.InitializeProcess
        self.RenderExecutableCallback += self.RenderExecutable
        self.RenderArgumentCallback += self.RenderArgument
        self.PreRenderTasksCallback += self.PreRenderTasks
        self.PostRenderTasksCallback += self.PostRenderTasks
    
    def Cleanup(self):
        for stdoutHandler in self.StdoutHandlers:
            del stdoutHandler.HandleCallback
        
        del self.InitializeProcessCallback
        del self.RenderExecutableCallback
        del self.RenderArgumentCallback
        del self.PreRenderTasksCallback
        del self.PostRenderTasksCallback
    
    def InitializeProcess( self ):
        # Set the process specific settings.
        self.ProcessPriority = ProcessPriorityClass.BelowNormal
        self.UseProcessTree = True
        self.PopupHandling = True
        self.StdoutHandling = True
        
        # Set the stdout handlers.
        self.AddStdoutHandlerCallback( "READY FOR INPUT" ).HandleCallback +=  self.HandleReadyForInput
        self.AddStdoutHandlerCallback( ".*ERROR:.*" ).HandleCallback += self.HandleError
        self.AddStdoutHandlerCallback( ".*Error:.*" ).HandleCallback += self.HandleError
        self.AddStdoutHandlerCallback( ".*Error :.*" ).HandleCallback += self.HandleError
        self.AddStdoutHandlerCallback( "Eddy\\[ERROR\\]" ).HandleCallback += self.HandleError
        #self.AddStdoutHandler( ".* seconds to execute", self.HandleProgress )
        #self.AddStdoutHandler( ".* took [0-9]*\\.[0-9]* seconds", self.HandleProgress )
        self.AddStdoutHandlerCallback( "Frame [0-9]+ \\(([0-9]+) of ([0-9]+)\\)" ).HandleCallback += self.HandleProgress

        # Handle QuickTime popup dialog
        # "QuickTime does not support the current Display Setting.  Please change it and restart this application."
        self.AddPopupHandler( "Unsupported Display", "OK" )
        self.AddPopupHandler( "Nicht.*", "OK" )
    
    def PreRenderTasks( self ):
        sceneFilename = self.deadlinePlugin.GetPluginInfoEntryWithDefault( "SceneFile", self.deadlinePlugin.GetDataFilename() )
        sceneFilename = RepositoryUtils.CheckPathMapping( sceneFilename )

        enablePathMapping = self.deadlinePlugin.GetBooleanConfigEntryWithDefault( "EnablePathMapping", True )
        self.deadlinePlugin.LogInfo( "Enable Path Mapping: %s" % enablePathMapping )
        
        if enablePathMapping:
            tempSceneDirectory = self.deadlinePlugin.CreateTempDirectory( "thread" + str(self.deadlinePlugin.GetThreadNumber()) )

            if SystemUtils.IsRunningOnWindows():
                sceneFilename = sceneFilename.replace( "/", "\\" )
            else:
                sceneFilename = sceneFilename.replace( "\\", "/" )
            
            tempSceneFileName = Path.GetFileName( sceneFilename )
            self.TempSceneFilename = Path.Combine( tempSceneDirectory, tempSceneFileName )
            
            if SystemUtils.IsRunningOnWindows():
                self.TempSceneFilename = self.TempSceneFilename.replace( "/", "\\" )
                if sceneFilename.startswith( "\\" ) and not sceneFilename.startswith( "\\\\" ):
                    sceneFilename = "\\" + sceneFilename
                if sceneFilename.startswith( "/" ) and not sceneFilename.startswith( "//" ):
                    sceneFilename = "/" + sceneFilename
            else:
                self.TempSceneFilename = self.TempSceneFilename.replace( "\\", "/" )
            
            # First, replace all TCL escapes ('\]') with '_TCL_ESCAPE_', then replace the '\' path separators with '/', and then swap back in the orignal TCL escapes.
            # This is so that we don't mess up any embedded TCL statements in the output path.
            self.pathMappingWithFilePermissionFix( sceneFilename, self.TempSceneFilename, ("\\[","\\", "_TCL_ESCAPE_"), ("_TCL_ESCAPE_", "/", "\\[") )
        else:
            if SystemUtils.IsRunningOnWindows():
                self.TempSceneFilename = sceneFilename.replace( "/", "\\" )
            else:
                self.TempSceneFilename = sceneFilename.replace( "\\", "/" )        

    def PostRenderTasks( self ):
        if self.deadlinePlugin.GetBooleanConfigEntryWithDefault( "EnablePathMapping", True ):
            File.Delete( self.TempSceneFilename )

    ## Called by Deadline to get the render executable.
    def RenderExecutable( self ):
        exeKey = "RenderExecutable" + str( self.Version ).replace( ".", "_" )
        return self.deadlinePlugin.GetRenderExecutable( exeKey, "Nuke %s" % self.Version )


    ## Called by Deadline to get the render arguments.
    def RenderArgument( self ):
        # Enable verbosity (the '2' option is only available in Nuke 7 and later)
        renderarguments = ["-V 2"] #for logs from nuke        

        if self.deadlinePlugin.GetBooleanPluginInfoEntryWithDefault( "ContinueOnError", False ):
            self.deadlinePlugin.LogInfo( "An attempt will be made to render subsequent frames in the range if an error occurs" )
            renderarguments.append("--cont")    

        renderarguments.append(f"-F 1") #dummy frame argument for CopyCat

        copycatNode = self.deadlinePlugin.GetPluginInfoEntry("CopyCatNode")
        renderarguments.append("-X") 
        renderarguments.append(copycatNode) 
              
        gpuOverrides = self.GetGpuOverrides()
            
        if self.deadlinePlugin.GetBooleanPluginInfoEntryWithDefault( "UseGpu", False ):
            self.deadlinePlugin.LogInfo( "Enabling GPU rendering" )            
            renderarguments.append("--gpu")
            if len(gpuOverrides) > 1:
                gpuOverrides = [ gpuOverrides[ self.deadlinePlugin.GetThreadNumber() ] ]                
                renderarguments.append(",".join( gpuOverrides ))
                self.deadlinePlugin.LogInfo(f"Append GPUs: {','.join(gpuOverrides)}" )              
        
        self.deadlinePlugin.SetProcessEnvironmentVariable( "EDDY_DEVICE_LIST", ",".join(gpuOverrides) )
        
        renderarguments.append(self.TempSceneFilename)
        renderarguments = ' '.join(renderarguments)

        return renderarguments
    
    def GetGpuOverrides( self ):
        useGpu = self.deadlinePlugin.GetBooleanPluginInfoEntryWithDefault( "UseGpu", False )
        if not useGpu:
            return []
        
        useSpecificGpu = self.deadlinePlugin.GetBooleanPluginInfoEntryWithDefault( "UseSpecificGpu", False )
        gpusSelectDevices = ""
        if useSpecificGpu:
            gpusSelectDevices = self.deadlinePlugin.GetPluginInfoEntryWithDefault( "GpuOverride", "0"  )
        
        # If the number of gpus per task is set, then need to calculate the gpus to use.
        gpusPerTask = 0
        resultGPUs = []

        if self.deadlinePlugin.OverrideGpuAffinity():
            overrideGPUs = [ str( gpu ) for gpu in self.deadlinePlugin.GpuAffinity() ]

            if gpusPerTask == 0 and gpusSelectDevices != "":
                gpus = gpusSelectDevices.split( "," )
                notFoundGPUs = []
                for gpu in gpus:
                    if gpu in overrideGPUs:
                        resultGPUs.append( gpu )
                    else:
                        notFoundGPUs.append( gpu )
                
                if len( notFoundGPUs ) > 0:
                    self.deadlinePlugin.LogWarning( "The Worker is overriding its GPU affinity and the following GPUs do not match the Workers affinity so they will not be used: " + ",".join( notFoundGPUs ) )
                if len( resultGPUs ) == 0:
                    self.deadlinePlugin.FailRender( "The Worker does not have affinity for any of the GPUs specified in the job." )
            elif gpusPerTask > 0:
                if gpusPerTask > len( overrideGPUs ):
                    self.deadlinePlugin.LogWarning( "The Worker is overriding its GPU affinity and the Worker only has affinity for " + str( len( overrideGPUs ) ) + " Workers of the " + str( gpusPerTask ) + " requested." )
                    resultGPUs = overrideGPUs
                else:
                    resultGPUs = list( overrideGPUs )[:gpusPerTask]
            else:
                resultGPUs = overrideGPUs
        elif gpusPerTask == 0 and gpusSelectDevices != "":
            resultGPUs = gpusSelectDevices.split( "," )

        elif gpusPerTask > 0:
            gpuList = []
            for i in range( ( self.deadlinePlugin.GetThreadNumber() * gpusPerTask ), ( self.deadlinePlugin.GetThreadNumber() * gpusPerTask ) + gpusPerTask ):
                gpuList.append( str( i ) )
            resultGPUs = gpuList
        else:
            self.deadlinePlugin.LogWarning( "GPU affinity is enabled for Nuke but the Workers GPU affinity has not been set and no overrides have been set. Defaulting to GPU 0." )
            resultGPUs = ["0"]
        
        resultGPUs = list( resultGPUs )
        
        return resultGPUs
    
    def HandleError( self ):
        if( not self.deadlinePlugin.GetBooleanPluginInfoEntryWithDefault( "ContinueOnError", False ) ):
            self.deadlinePlugin.FailRender( self.GetRegexMatch( 0 ) )
        else:
            self.deadlinePlugin.LogWarning( "Skipping error detection as 'Continue On Error' is enabled." )

    def HandleProgress( self ):
        currFrame = int( self.GetRegexMatch( 1 ) )
        totalFrames = int( self.GetRegexMatch( 2 ) )
        if totalFrames != 0:
            self.deadlinePlugin.SetProgress( ( float(currFrame) / float(totalFrames) ) * 100.0 )
        self.deadlinePlugin.SetStatusMessage( self.GetRegexMatch( 0 ) )
    
    def HandleReadyForInput( self ):
        self.ReadyForInput = True
    
    def IsReadyForInput( self ):
        return self.ReadyForInput
    
    def ResetReadyForInput( self ):
        self.ReadyForInput = False
    
    def ReadyForInputCommand( self ):
        return "print( \"READY FOR INPUT\\n\" )"

