# from server_runtime.lifecycle_server import ServerLifeCycleServer
# from server_runtime.registry_server import RegistryServer
from server_runtime.repository_server import RepositoryServer
# from server_runtime.logging_server import LoggingServer

# TODO: start load balancer

# reg_server = RegistryServer("./registry")

# reg_pid = reg_server.start()
#
repo_server = RepositoryServer("./repository")

repo_pid = repo_server.start()
#
# life_server = ServerLifeCycleServer("./server_lifecycle_manager")
#
# life_server_pid = life_server.start()

# logging_server = LoggingServer("./logging")

# logging_server_pid = logging_server.start()
