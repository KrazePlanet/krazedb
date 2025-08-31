import argparse
import redis
import os
import json
import logging
import re
from datetime import datetime
from typing import Optional, Set, Dict, Any
from pathlib import Path
import subprocess
import gzip
import sys

# Define the version
__version__ = "v0.0.2"  # Current Version of krazedb

class DataStore:
    def __init__(self, host='localhost', port=6379, db=0, max_connections=10):
        self.pool = redis.ConnectionPool(
            host=host, port=port, db=db, max_connections=max_connections
        )
        self.r = redis.Redis(connection_pool=self.pool)
        self.logger = logging.getLogger(__name__)
        
        try:
            self.r.ping()
            self.logger.info(f"Connected to Redis at {host}:{port}")
        except redis.ConnectionError as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise

    def add_domain(self, project: str, domain: str) -> int:
        try:
            return self.r.sadd(project, domain)
        except redis.RedisError as e:
            self.logger.error(f"Failed to add domain {domain} to project {project}: {e}")
            raise

    def remove_domain(self, project: str, domain: str) -> int:
        """Remove a domain from a project"""
        try:
            return self.r.srem(project, domain)
        except redis.RedisError as e:
            self.logger.error(f"Failed to remove domain {domain} from project {project}: {e}")
            raise

    def get_domains(self, project: str) -> Set[bytes]:
        try:
            return self.r.smembers(project)
        except redis.RedisError as e:
            self.logger.error(f"Failed to get domains for project {project}: {e}")
            raise

    def deduplicate(self, project):
        return True

    def delete_project(self, project: str) -> int:
        try:
            return self.r.delete(project)
        except redis.RedisError as e:
            self.logger.error(f"Failed to delete project {project}: {e}")
            raise
    
    def project_exists(self, project: str) -> bool:
        try:
            return bool(self.r.exists(project))
        except redis.RedisError as e:
            self.logger.error(f"Failed to check if project {project} exists: {e}")
            raise

    def count_domains(self, project: str) -> int:
        try:
            return self.r.scard(project)
        except redis.RedisError as e:
            self.logger.error(f"Failed to count domains for project {project}: {e}")
            raise

    def get_all_projects(self) -> Set[str]:
        """Get all project names stored in Redis"""
        try:
            # Get all keys in Redis (project names)
            raw_keys = self.r.keys('*')
            return {key.decode('utf-8') for key in raw_keys}
        except redis.RedisError as e:
            self.logger.error(f"Failed to get all projects: {e}")
            raise
            
class DomainValidator:


    # Single comprehensive regex pattern that handles all valid domain formats:
    # - Leading wildcards: *.example.com
    # - Internal wildcards: svc-*.domain.com, rac-*.net.dell.com, test.*.invalid.com
    # - Service records: _service.domain.com, _collab-edge.5g.dell.com
    # - Standard domains: example.com, sub.domain.com
    DOMAIN_PATTERN = re.compile(
        r'^(?:'
        r'(?:\*\.)?'  # Optional leading wildcard: *.
        r'(?:[a-zA-Z0-9_*](?:[a-zA-Z0-9_*-]{0,61}[a-zA-Z0-9_*])?\.)'  # Labels (allows * anywhere in label)
        r'+'  # One or more labels
        r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'  # TLD (no * or _ allowed)
        r')$'
    )
    
    @classmethod
    def is_valid_domain(cls, domain: str) -> bool:
        if not domain or len(domain) > 253:
            return False
        
        # Check for invalid patterns that the regex might miss
        if domain.startswith('*') and not domain.startswith('*.'):
            return False  # *abc.com is invalid
        
        if domain.endswith('*') or domain == '*':
            return False  # svc-* without TLD is invalid
        
        if '.-' in domain or '-.' in domain or domain.startswith('.') or domain.endswith('.'):
            return False  # -.example.com and similar invalid patterns
        
        return bool(cls.DOMAIN_PATTERN.match(domain))

class ConfigManager:
    
    def __init__(self, config_file: Optional[str] = None):
        self.config = self._load_config(config_file)
        self.logger = logging.getLogger(__name__)
    
    def _load_config(self, config_file: Optional[str]) -> Dict[str, Any]:
        default_config = {
            'redis': {
                'host': 'localhost',
                'port': 6379,
                'db': 0,
                'max_connections': 10
            },
            'logging': {
                'level': 'INFO',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        }
        
        if config_file and Path(config_file).exists():
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                    for section, values in file_config.items():
                        if section in default_config:
                            default_config[section].update(values)
                        else:
                            default_config[section] = values
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Failed to load config file {config_file}: {e}")
        
        redis_host = os.getenv('REDIS_HOST')
        if redis_host:
            default_config['redis']['host'] = redis_host
        
        redis_port = os.getenv('REDIS_PORT')
        if redis_port:
            try:
                default_config['redis']['port'] = int(redis_port)
            except ValueError:
                logging.warning(f"Invalid REDIS_PORT value: {redis_port}")
        
        return default_config
    
    def get_redis_config(self) -> Dict[str, Any]:
        return self.config['redis']
    
    def get_logging_config(self) -> Dict[str, Any]:
        return self.config['logging']

class Project:
    def __init__(self, datastore, name: str):
        self.datastore = datastore
        self.name = name
        self.logger = logging.getLogger(__name__)
    
    def export_domains(self, output_file: str, format_type: str = 'text') -> bool:
        try:
            domains = self.get_domains()
            if not domains:
                self.logger.warning(f"No domains found in project '{self.name}'")
                return False
            
            output_path = Path(output_file)
            
            if format_type.lower() == 'json':
                export_data = {
                    'project': self.name,
                    'domain_count': len(domains),
                    'exported_at': str(datetime.now().isoformat()),
                    'domains': sorted(list(domains))
                }
                
                with open(output_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
                    
            elif format_type.lower() == 'text':
                with open(output_path, 'w') as f:
                    for domain in sorted(domains):
                        f.write(f"{domain}\n")
            else:
                self.logger.error(f"Unsupported export format: {format_type}")
                return False
            
            self.logger.info(f"Exported {len(domains)} domains to {output_file} ({format_type} format)")
            return True
            
        except (IOError, json.JSONEncodeError) as e:
            self.logger.error(f"Failed to export domains: {e}")
            return False

    def _process_domain(self, domain: str) -> str:
        """Normalize domain input (similar to sed filters)."""
        domain = domain.strip()

        # Apply the filters
        domain = re.sub(r'^\*\.', '', domain)       # remove leading *.
        domain = re.sub(r'^\*', '', domain)         # remove leading *
        domain = re.sub(r'^\.', '', domain)         # remove leading .
        domain = re.sub(r'^https?://', '', domain)  # remove leading http:// or https://
        domain = re.sub(r'^www\.', '', domain)      # remove leading www.

        return domain.lower()

    def add_domains_from_file(self, filename: str, validate: bool = True) -> None:
        if filename == "-":  # Read from stdin
            file_obj = sys.stdin
            file_path = None
        else:
            file_path = Path(filename)
            if not file_path.exists():
                self.logger.error(f"File {filename} does not exist")
                return
            # Open normally or as gzip
            if file_path.suffix == ".gz":
                file_obj = gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore')
            else:
                file_obj = open(file_path, 'r', encoding='utf-8', errors='ignore')

        try:
            with file_obj:
                total_domains = 0
                new_domains = 0
                invalid_domains = 0
                
                for line_num, line in enumerate(file_obj, 1):
                    domain = line.strip().strip('\r')
                    if not domain:
                        continue
                    
                    processed_domain = self._process_domain(domain)

                    if validate:
                        if not DomainValidator.is_valid_domain(domain):
                            self.logger.warning(f"Invalid domain '{domain}' on line {line_num}, skipping")
                            invalid_domains += 1
                            continue
                    else:
                        processed_domain = domain  # save as-is
                    
                    try:
                        added = self.datastore.add_domain(self.name, processed_domain)
                        new_domains += added
                        total_domains += 1
                        if domain != processed_domain:
                            self.logger.debug(f"Processed domain '{domain}' as '{processed_domain}'")
                    except redis.RedisError as e:
                        self.logger.error(f"Failed to add domain '{processed_domain}': {e}")
                
                duplicate_domains = total_domains - new_domains
                duplicate_percentage = (duplicate_domains / total_domains * 100) if total_domains > 0 else 0
                
                self.logger.info(
                    f"Processed {total_domains} domains: {new_domains} new, "
                    f"{duplicate_domains} duplicates ({duplicate_percentage:.2f}%)"
                )
                if invalid_domains > 0:
                    self.logger.warning(f"Skipped {invalid_domains} invalid domains")
                    
        except IOError as e:
            self.logger.error(f"Failed to read file {filename}: {e}")

    def remove_domains_from_file(self, filename: str) -> None:
        """Remove domains listed in a file from the project"""
        if filename == "-":  # Read from stdin
            file_obj = sys.stdin
            file_path = None
        else:
            file_path = Path(filename)
            if not file_path.exists():
                self.logger.error(f"File {filename} does not exist")
                return
            # Open normally or as gzip
            if file_path.suffix == ".gz":
                file_obj = gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore')
            else:
                file_obj = open(file_path, 'r', encoding='utf-8', errors='ignore')

        try:
            with file_obj:
                total_domains = 0
                removed_domains = 0
                not_found_domains = 0
                
                for line_num, line in enumerate(file_obj, 1):
                    domain = line.strip().strip('\r')
                    if not domain:
                        continue
                    
                    try:
                        removed = self.datastore.remove_domain(self.name, domain)
                        if removed > 0:
                            removed_domains += 1
                        else:
                            not_found_domains += 1
                            self.logger.warning(f"Domain '{domain}' not found in project '{self.name}'")
                        total_domains += 1
                    except redis.RedisError as e:
                        self.logger.error(f"Failed to remove domain '{domain}': {e}")
                
                self.logger.info(
                    f"Processed {total_domains} domains: {removed_domains} removed, "
                    f"{not_found_domains} not found"
                )
                    
        except IOError as e:
            self.logger.error(f"Failed to read file {filename}: {e}")

    def remove_domain(self, domain: str) -> bool:
        """Remove a single domain from the project"""
        try:
            removed = self.datastore.remove_domain(self.name, domain)
            if removed > 0:
                self.logger.info(f"Removed domain '{domain}' from project '{self.name}'")
                return True
            else:
                self.logger.warning(f"Domain '{domain}' not found in project '{self.name}'")
                return False
        except redis.RedisError as e:
            self.logger.error(f"Failed to remove domain '{domain}': {e}")
            return False

    def get_domains(self) -> Set[str]:
        try:
            raw_domains = self.datastore.get_domains(self.name)
            return {domain.decode('utf-8') for domain in raw_domains}
        except redis.RedisError as e:
            self.logger.error(f"Failed to get domains: {e}")
            return set()
    
    def count_domains(self) -> Optional[int]:
        try:
            if not self.datastore.project_exists(self.name):
                self.logger.error(f"Project '{self.name}' does not exist")
                return None
            
            count = self.datastore.count_domains(self.name)
            self.logger.info(f"Project '{self.name}' contains {count} domains")
            return count
        except redis.RedisError as e:
            self.logger.error(f"Failed to count domains: {e}")
            return None

    def deduplicate(self) -> bool:
        return self.datastore.deduplicate(self.name)
    
    def delete(self) -> bool:
        try:
            self.logger.info(f"Attempting to delete project '{self.name}'")
            deleted_count = self.datastore.delete_project(self.name)
            
            if deleted_count == 0:
                self.logger.warning(f"Project '{self.name}' did not exist")
                return False
            else:
                self.logger.info(f"Project '{self.name}' deleted successfully")
                return True
        except redis.RedisError as e:
            self.logger.error(f"Failed to delete project: {e}")
            return False

    @classmethod
    def get_all_projects(cls, datastore) -> Set[str]:
        """Get all project names from the datastore"""
        try:
            return datastore.get_all_projects()
        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Failed to get all projects: {e}")
            return set()

def setup_logging(config: ConfigManager) -> None:
    logging_config = config.get_logging_config()
    
    logging.basicConfig(
        level=getattr(logging, logging_config['level']),
        format=logging_config['format'],
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('krazedb.log')
        ]
    )

def main():
    parser = argparse.ArgumentParser(
        description="Manage bug bounty targets",
        formatter_class=argparse.RawDescriptionHelpFormatter,        epilog="""
Examples:
  %(prog)s add -p myproject -f domains.txt
  %(prog)s export -p myproject -f output.json --format json
  %(prog)s count -p myproject
  %(prog)s projects
  %(prog)s remove -p myproject -f domains_to_remove.txt
  %(prog)s remove -p myproject -d example.com
  %(prog)s delete -p myproject
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    add_parser = subparsers.add_parser('add', help='Add domains from file')
    add_parser.add_argument('-p', '--project', required=True, help='Project name')
    add_parser.add_argument('-f', '--file', required=True, help='File containing domains')
    add_parser.add_argument('--no-validate', action='store_true', help='Skip domain validation')
    
    export_parser = subparsers.add_parser('export', help='Export domains to file')
    export_parser.add_argument('-p', '--project', required=True, help='Project name')
    export_parser.add_argument('-f', '--file', required=True, help='Output file')
    export_parser.add_argument('--format', choices=['text', 'json'], default='text', help='Export format')
    
    print_parser = subparsers.add_parser('print', help='Print all domains')
    print_parser.add_argument('-p', '--project', required=True, help='Project name')
    print_parser.add_argument('-d', '--domain', help='Filter by base domain (e.g., dell.com)')

    count_parser = subparsers.add_parser('count', help='Count domains in project')
    count_parser.add_argument('-p', '--project', required=True, help='Project name')
    
    projects_parser = subparsers.add_parser('projects', help='List all project names')

    remove_parser = subparsers.add_parser('remove', help='Remove domains from project')
    remove_parser.add_argument('-p', '--project', required=True, help='Project name')
    remove_group = remove_parser.add_mutually_exclusive_group(required=True)
    remove_group.add_argument('-f', '--file', help='File containing domains to remove')
    remove_group.add_argument('-d', '--domain', help='Single domain to remove')
    
    delete_parser = subparsers.add_parser('delete', help='Delete project')
    delete_parser.add_argument('-p', '--project', required=True, help='Project name')
    delete_parser.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    
    parser.add_argument('-c', '--config', help='Configuration file path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')

    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__, help='Show current version of krazedb')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    config = ConfigManager(args.config)
    
    if args.verbose:
        config.config['logging']['level'] = 'DEBUG'
    
    setup_logging(config)
    logger = logging.getLogger(__name__)
    
    try:
        redis_config = config.get_redis_config()
        datastore = DataStore(**redis_config)
          # Only create project object if command requires it
        if args.command in ['add', 'export', 'print', 'count', 'remove', 'delete']:
            project = Project(datastore, args.project)
        
    except redis.ConnectionError:
        logger.error("Failed to connect to Redis. Please check your Redis server is running.")
        return 1
    except Exception as e:
        logger.error(f"Initialisation error: {e}")
        return 1

    if args.command == 'add':
        validate = not args.no_validate
        project.add_domains_from_file(args.file, validate=validate)
        project.deduplicate()
        
    elif args.command == 'export':
        if not project.export_domains(args.file, args.format):
            return 1
            
    elif args.command == 'print':
        domains = project.get_domains()
        if not domains:
            logger.warning(f"No domains found in project '{args.project}'")
        else:
            if args.domain:
                # filter domains ending with the given base domain
                filtered = [d for d in sorted(domains) if d.endswith(args.domain)]
                if not filtered:
                    logger.warning(f"No subdomains found for {args.domain}")
                else:
                    # use tldinfo for formatting
                    try:
                        proc = subprocess.run(
                            ["tldinfo", "--silent", "--extract", "subdomain,domain,suffix"],
                            input="\n".join(filtered),
                            text=True,
                            capture_output=True,
                            check=True
                        )
                        print(proc.stdout.strip())
                    except subprocess.CalledProcessError as e:
                        logger.error(f"tldinfo failed: {e.stderr}")
            else:
                for domain in sorted(domains):
                    print(domain)
                
    elif args.command == 'count':
        count = project.count_domains()
        if count is not None:
            print(f"{count}")
        else:
            return 1

    elif args.command == 'projects':
        projects = Project.get_all_projects(datastore)
        if not projects:
            logger.warning("No projects found in Redis")
        else:
            for project_name in sorted(projects):
                print(project_name)
    
    elif args.command == 'remove':
        if args.file:
            project.remove_domains_from_file(args.file)
        elif args.domain:
            if project.remove_domain(args.domain):
                print(f"Domain '{args.domain}' removed from project '{args.project}'")
            else:
                return 1
            
    elif args.command == 'delete':
        if not args.yes:
            response = input(f"Are you sure you want to delete project '{args.project}'? (y/N): ")
            if response.lower() not in ['y', 'yes']:
                logger.info("Delete operation cancelled")
                return 0
        
        if project.delete():
            print(f"Project '{args.project}' deleted successfully")
        else:
            return 1
    
    return 0

if __name__ == '__main__':
    try:
        exit_code = main()
        exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        exit(1)
