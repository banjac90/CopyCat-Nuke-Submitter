# Plugin

## Location for plugin
This plugin is custom plugin for Nuke, but we have removed unnecessary components that are not required for the CopyCat node.
Copy `CopyCat` folder with it content into the custom plugin directory in your repository: `RepoPath/custom/plugins`
The basic functionality of this plugin is to execute the Nuke CopyCat command with specific arguments for CopyCat, as outlined in the Nuke [documentation](https://learn.foundry.com/nuke/content/comp_environment/air_tools/cc-dist-manager.html) 
The plugin also set the environment for Distributed training.

### Param file
In Param file is added specific parameters important for CopyCat process.
Parameters include:
- MainMachine - The main machine for training.
- MainMachineIP - The IP address of the main machine (either IPv4 or IPv6). This is used to set the `COPYCAT_LOCAL_ADDR` or `COPYCAT_MAIN_ADDR` variables
- UseIPv6 - Specifies whether to use only IPv6 if is `true` or IPv4 addresses `false`. 
- Port - default is 3000, it set `COPYCAT_MAIN_PORT`variable
- TrainingSlaves - list of machines for training and first machine (0 list index) must be MainMachine
- SyncInterval - sets `COPYCAT_SYNC_INTERVAL` variable

### Option file
Options are:
- CopyCatNode: The name of the CopyCat node you want to train. This option specifies the node name, which is used as an argument during the plugin process
- WorldSize: The number of machines for training. This value is fixed and should not be changed. Based on this option, the plugin sets the `COPYCAT_WORLD_SIZE` and `COPYCAT_RANK` variables for each machine.

The rest of option and params are inherited from Nuke plugin and they are considered useful (example: `GpuOverride`).

## Functionality
`CopyCat.py` is responsible for setting up the necessary variables for CopyCat's distributed training. It sets the world size, node ranks, main machine's IP addresses (both IPv4 and IPv6) and other important variables for this Nuke process. The plugin heavily relies on the submitter, which interacts with the Deadline web interface. This functionality has been developed in its current form and will be improved in future versions.

To fully understand the implementation, it is recommended to read through the `CopyCat.py` file, as it contains the code that defines the process.

# Submitter

The submitter is a standalone GUI for job submission, where you can define all the necessary information. In this version, you will need to configure it for your specific pipeline. Additionally, it requires the [Standalone Python API and Deadline Web Service](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/standalone-python.html) for now. 

## Requirements
 - [Standalone Python API and Deadline Web Service](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/standalone-python.html)
 - CopyCat pool (optional)
 - CopyCat group (optional)
  
 ## How to use:
 1. Copy the scripts from our **Client** folder into your custom client folder. The scripts include the following files: 
	 - `menu.py` 
	 - `DeadlineStandaloneCopyCatClient.py` 
 Feel free to modify these scripts to suit your pipeline.
 
 2. In `SubmitNukeCopyCat.py`  needs to be modified:
 - DEADLINE_WEBSERVICE_URL - your web service address
 - DEADLINE_WEBSERVICE_PORT - web service port
 - CUSTOM_DEADLINE_API_LOCATION - location to your api folder

3. Once the modifications are made, launch Nuke and check if the "Submit CopyCat To Deadline" option appears in the Thinkbox menu.

## How to use
1. You need to select CopyCat node
2. Then click in menu "Submit CopyCat To Deadline"

Now you will get popup windows with parameters.
[Submitter image](./copycatclient.png)

**Client contains:**
- Group and Pool Detection: The submitter will attempt to retrieve the CopyCat group and pool. If any are set and contain machines, it will provide a list of available machines. It will also automatically fill in the `MainMachine` (If any) and the node to render/train field.
- IP Address Retrieval: The submitter will try to ping and detect the IP address of Main machine. If successful, it will automatically set it. 
- Port Configuration: The default port is set to 3000.
- Job Name: The job name is automatically set to the name of the script.
- World Size: The world size is determined by the number of machines found in the Machines for Job field 
- Machines for Job: The machine name list is a comma-separated list of machines. **The `MainMachine` name must be the first machine in the list.** If it's not, the submitter will automatically reorder the list and place it first when submitting.
- Sync Interval: The sync interval for CopyCat will be set based on the value provided.
For better understanding of variables and fields read [Nuke documentation for CopyCat distributed setup](https://learn.foundry.com/nuke/content/comp_environment/air_tools/cc-dist-manual.html) .
**All of those fields are required.**

## How it works
**Steps:**
1. Preform necessary checks on the inserted values before creating `pluginInfo` and `jobInfo` dictionaries
2. It will set up the `pluginInfo` and `jobInfo` dictionaries for job submission via the API.
3. The plugin will verify the connection and attempt to submit the job using the Deadline API

The frame range in `jobInfo` is automatically  set from 1 to world size (the number of machines). Since the frame range in Deadline corresponds to the number of tasks, this is used to create a separate job for each machine.

After submitting a job, connect to the worker log via the Deadline Monitor on any machine from the pool that has taken the job. In the log, you should see entries related to the setup of variables, as well as logs from CopyCat indicating the machine's specific rank and that it is waiting for others to join. Once the other machines join, the training process will begin.
**IMPORTANT**
The machines used for training must be on the same network interface and be able to communicate with each other for CopyCat to function properly.

Future goals:
- In the next version, our plan is to implement `jobInfo` and `plugIninfo` files, similar to how other Deadline plugins are structured.
