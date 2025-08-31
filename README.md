## KrazeDb 🎯

<details>
  <summary><b>Prerequisites</b></summary>

You'll need **Redis** installed and running on your system.

### Installing Redis

#### **Linux (Ubuntu/Debian)**
```bash
sudo apt update
sudo apt install redis-server redis-tools

# Start Redis service
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### **Linux (RHEL/CentOS/Fedora)**
```bash
sudo dnf install redis
# or for older systems: sudo yum install redis

# Start Redis service
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### **Windows**
```powershell
# Using Chocolatey
choco install redis-64

# Or download from: https://github.com/microsoftarchive/redis/releases
# Then run: redis-server.exe
```

#### **macOS**
```bash
brew install redis
brew services start redis
```

### Python Dependencies
```bash
pip install redis
# or
pip install -r requirements.txt
```

## Configuration

### Default Configuration
Create `config.json` for custom Redis settings:
```json
{
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0,
    "max_connections": 10
  },
  "logging": {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  }
}
```

### Environment Variables
Override settings with environment variables:
```bash
export REDIS_HOST=my-redis-server
export REDIS_PORT=6380
```
</details>


### Installing krazedb
```
git clone https://github.com/rix4uni/krazedb.git
cd krazedb
python3 setup.py install
```

## pipx
Quick setup in isolated python environment using [pipx](https://pypa.github.io/pipx/)
```
pipx install --force git+https://github.com/rix4uni/krazedb.git
```

## Usage
```
usage: krazedb [-h] [-c CONFIG] [-v] [--version] {add,export,print,count,projects,remove,delete} ...

Manage bug bounty targets

positional arguments:
  {add,export,print,count,projects,remove,delete}
                        Available commands
    add                 Add domains from file
    export              Export domains to file
    print               Print all domains
    count               Count domains in project
    projects            List all project names
    remove              Remove domains from project
    delete              Delete project

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Configuration file path
  -v, --verbose         Enable verbose logging
  --version             Show current version of krazedb

Examples:
  krazedb add -p myproject -f domains.txt
  krazedb export -p myproject -f output.json --format json
  krazedb count -p myproject
  krazedb projects
  krazedb remove -p myproject -f domains_to_remove.txt
  krazedb remove -p myproject -d example.com
  krazedb delete -p myproject
```