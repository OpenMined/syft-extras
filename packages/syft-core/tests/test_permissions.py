import pytest
import tempfile
from pathlib import Path
import yaml

from syft_core.permissions import (
    SyftPermission, PermissionRule, PermissionType, ComputedPermission,
    get_computed_permission, PERM_FILE, OLD_PERM_FILE,
    set_auto_convert_permissions, get_auto_convert_permissions
)
from syft_core import Client
from syft_core.config import SyftClientConfig
from syft_core.types import RelativePath


class MockContext:
    def __init__(self, email: str, workspace_dir: Path):
        self.email = email
        self.workspace = MockWorkspace(workspace_dir)


class MockWorkspace:
    def __init__(self, datasites_dir: Path):
        self.datasites = datasites_dir


def create_client(email: str, workspace_dir: Path) -> Client:
    """Create a Client instance for testing"""
    config = SyftClientConfig(
        email=email,
        data_dir=workspace_dir,
        server_url="http://localhost:8080",
        client_url="http://127.0.0.1:8082",
        path=workspace_dir / "config.yaml"
    )
    return Client(config)


class TestNewPermissionFormat:
    """Test the new syft.pub.yaml format with terminal flag and access object"""
    
    def test_parse_new_format_basic(self):
        """Test parsing basic new format with access object"""
        yaml_content = {
            "rules": [
                {
                    "pattern": "**",
                    "access": {
                        "read": ["*"],
                        "write": ["alice@example.com"],
                        "admin": ["owner@example.com"]
                    }
                }
            ]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        
        # Should create 3 rules, one for each user
        assert len(perm.rules) == 3
        assert not perm.terminal
        
        # Check admin rule
        admin_rules = [r for r in perm.rules if "owner@example.com" in r.user]
        assert len(admin_rules) == 1
        assert PermissionType.ADMIN in admin_rules[0].permissions
        assert PermissionType.WRITE in admin_rules[0].permissions
        assert PermissionType.READ in admin_rules[0].permissions
        
        # Check write rule
        write_rules = [r for r in perm.rules if "alice@example.com" in r.user]
        assert len(write_rules) == 1
        assert PermissionType.WRITE in write_rules[0].permissions
        assert PermissionType.READ in write_rules[0].permissions
        assert PermissionType.ADMIN not in write_rules[0].permissions
        
        # Check read rule
        read_rules = [r for r in perm.rules if "*" in r.user]
        assert len(read_rules) == 1
        assert PermissionType.READ in read_rules[0].permissions
        assert PermissionType.WRITE not in read_rules[0].permissions
    
    def test_terminal_flag(self):
        """Test terminal flag stops inheritance"""
        yaml_content = {
            "terminal": True,
            "rules": [
                {
                    "pattern": "**",
                    "access": {
                        "read": ["*"]
                    }
                }
            ]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        assert perm.terminal
        assert perm.rules[0].terminal
    
    def test_save_new_format(self):
        """Test saving permissions in new format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            datasites_dir = workspace_dir / "datasites"
            datasites_dir.mkdir(parents=True)
            context = MockContext("owner@example.com", workspace_dir)
            
            perm = SyftPermission.mine_with_public_read(context, Path(tmpdir) / "test")
            perm.save(Path(tmpdir) / "test")
            
            # Read back and verify format
            with open(Path(tmpdir) / "test" / PERM_FILE, "r") as f:
                saved = yaml.safe_load(f)
            
            assert saved["terminal"] == True
            assert len(saved["rules"]) == 1
            assert saved["rules"][0]["pattern"] == "**"
            assert "owner@example.com" in saved["rules"][0]["access"]["admin"]
            assert "*" in saved["rules"][0]["access"]["read"]
    
    def test_multiple_patterns(self):
        """Test multiple patterns in new format"""
        yaml_content = {
            "rules": [
                {
                    "pattern": "*.md",
                    "access": {
                        "read": ["*"]
                    }
                },
                {
                    "pattern": "private/*.txt",
                    "access": {
                        "read": ["alice@example.com"],
                        "write": ["alice@example.com"]
                    }
                },
                {
                    "pattern": "**",
                    "access": {}
                }
            ]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        
        # Should have rules for each pattern (except empty access pattern)
        patterns = [r.path for r in perm.rules]
        assert "*.md" in patterns
        assert "private/*.txt" in patterns
        # Pattern with empty access object creates no rules
        assert len([r for r in perm.rules if r.path == "**"]) == 0
    
    def test_legacy_format_compatibility(self):
        """Test that old format still works"""
        yaml_content = [
            {
                "path": "**",
                "user": "*",
                "permissions": ["read"]
            },
            {
                "path": "**",
                "user": "owner@example.com",
                "permissions": ["admin"]
            }
        ]
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        assert len(perm.rules) == 2
        assert not perm.terminal
    
    def test_computed_permissions_with_terminal(self):
        """Test that terminal flag stops inheritance correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create parent permission (public read)
            parent_dir = datasites / "owner"
            parent_dir.mkdir(parents=True)
            parent_perm = {
                "rules": [{
                    "pattern": "**",
                    "access": {
                        "read": ["*"]
                    }
                }]
            }
            with open(parent_dir / PERM_FILE, "w") as f:
                yaml.dump(parent_perm, f)
            
            # Create child permission with terminal (private)
            child_dir = parent_dir / "private"
            child_dir.mkdir(parents=True)
            child_perm = {
                "terminal": True,
                "rules": [{
                    "pattern": "**",
                    "access": {
                        "read": ["owner@example.com"]
                    }
                }]
            }
            with open(child_dir / PERM_FILE, "w") as f:
                yaml.dump(child_perm, f)
            
            # Test access
            client = create_client("stranger@example.com", datasites.parent)
            
            # Should have access to parent
            parent_perms = get_computed_permission(
                client=client,
                path=RelativePath("owner/file.txt")
            )
            assert parent_perms.has_permission(PermissionType.READ)
            
            # Should NOT have access to child (terminal stops inheritance)
            child_perms = get_computed_permission(
                client=client,
                path=RelativePath("owner/private/secret.txt")
            )
            assert not child_perms.has_permission(PermissionType.READ)
    
    def test_permission_hierarchy(self):
        """Test admin > write > read hierarchy"""
        yaml_content = {
            "rules": [{
                "pattern": "**",
                "access": {
                    "read": ["reader@example.com"],
                    "write": ["writer@example.com"],
                    "admin": ["admin@example.com"]
                }
            }]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        
        # Find rules for each user
        reader_rule = next(r for r in perm.rules if r.user == "reader@example.com")
        writer_rule = next(r for r in perm.rules if r.user == "writer@example.com")
        admin_rule = next(r for r in perm.rules if r.user == "admin@example.com")
        
        # Reader should only have read
        assert PermissionType.READ in reader_rule.permissions
        assert PermissionType.WRITE not in reader_rule.permissions
        assert PermissionType.ADMIN not in reader_rule.permissions
        
        # Writer should have write and read
        assert PermissionType.READ in writer_rule.permissions
        assert PermissionType.WRITE in writer_rule.permissions
        assert PermissionType.CREATE in writer_rule.permissions
        assert PermissionType.ADMIN not in writer_rule.permissions
        
        # Admin should have everything
        assert PermissionType.READ in admin_rule.permissions
        assert PermissionType.WRITE in admin_rule.permissions
        assert PermissionType.CREATE in admin_rule.permissions
        assert PermissionType.ADMIN in admin_rule.permissions
    
    def test_empty_access_object(self):
        """Test pattern with empty access object (no permissions)"""
        yaml_content = {
            "rules": [{
                "pattern": "**",
                "access": {}
            }]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        assert len(perm.rules) == 0  # No rules created for empty access
    
    def test_glob_patterns(self):
        """Test various glob patterns work correctly"""
        yaml_content = {
            "rules": [
                {
                    "pattern": "*.txt",
                    "access": {"read": ["*"]}
                },
                {
                    "pattern": "data/**/*.csv",
                    "access": {"read": ["analyst@example.com"]}
                },
                {
                    "pattern": "src/**",
                    "access": {"write": ["dev@example.com"]}
                }
            ]
        }
        
        perm = SyftPermission.from_rule_dicts(Path("test/syft.pub.yaml"), yaml_content)
        
        # Check patterns are preserved
        patterns = [r.path for r in perm.rules]
        assert "*.txt" in patterns
        assert "data/**/*.csv" in patterns
        assert "src/**" in patterns
    
    def test_datasite_default_permissions(self):
        """Test default datasite permissions creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir)
            datasites_dir = workspace_dir / "datasites"
            datasites_dir.mkdir(parents=True)
            context = MockContext("owner@example.com", workspace_dir)
            
            perm = SyftPermission.datasite_default(context, Path(tmpdir) / "owner")
            
            # Should have one rule for owner with all permissions
            assert len(perm.rules) == 1
            rule = perm.rules[0]
            assert rule.user == "owner@example.com"
            assert rule.path == "**"
            assert PermissionType.ADMIN in rule.permissions
            assert PermissionType.WRITE in rule.permissions
            assert PermissionType.CREATE in rule.permissions
            assert PermissionType.READ in rule.permissions


class TestOldFormatConversion:
    """Test conversion from old syftperm.yaml to new syft.pub.yaml format"""
    
    def setup_method(self):
        """Save original auto-convert setting"""
        self.original_setting = get_auto_convert_permissions()
    
    def teardown_method(self):
        """Restore original auto-convert setting"""
        set_auto_convert_permissions(self.original_setting)
    
    def test_old_format_auto_conversion(self):
        """Test automatic conversion from old to new format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create old format file
            old_content = [
                {
                    "path": "**/*.txt",
                    "user": "*",
                    "permissions": ["read"]
                },
                {
                    "path": "private/*",
                    "user": "owner@example.com",
                    "permissions": ["admin", "write", "read"]
                }
            ]
            
            test_dir = datasites / "test"
            test_dir.mkdir(parents=True)
            old_file = test_dir / OLD_PERM_FILE
            new_file = test_dir / PERM_FILE
            
            with open(old_file, "w") as f:
                yaml.dump(old_content, f)
            
            # Enable auto-conversion
            set_auto_convert_permissions(True)
            
            # Load permission file (should trigger conversion)
            perm = SyftPermission.from_file(new_file, datasites)
            
            # Check old file is deleted
            assert not old_file.exists()
            
            # Check new file exists
            assert new_file.exists()
            
            # Verify content was converted correctly
            with open(new_file, "r") as f:
                new_content = yaml.safe_load(f)
            
            assert "rules" in new_content
            assert len(new_content["rules"]) == 2
            
            # Check first rule
            rule1 = new_content["rules"][0]
            assert rule1["pattern"] == "**/*.txt"
            assert "*" in rule1["access"]["read"]
            
            # Check second rule
            rule2 = new_content["rules"][1]
            assert rule2["pattern"] == "private/*"
            assert "owner@example.com" in rule2["access"]["admin"]
    
    def test_old_format_conversion_disabled(self):
        """Test that conversion doesn't happen when disabled"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create old format file
            old_content = [
                {
                    "path": "**",
                    "user": "*",
                    "permissions": ["read"]
                }
            ]
            
            test_dir = datasites / "test"
            test_dir.mkdir(parents=True)
            old_file = test_dir / OLD_PERM_FILE
            new_file = test_dir / PERM_FILE
            
            with open(old_file, "w") as f:
                yaml.dump(old_content, f)
            
            # Disable auto-conversion
            set_auto_convert_permissions(False)
            
            # Try to load new file (should fail)
            with pytest.raises(FileNotFoundError):
                SyftPermission.from_file(new_file, datasites)
            
            # Old file should still exist
            assert old_file.exists()
            assert not new_file.exists()
    
    def test_complex_old_format_conversion(self):
        """Test conversion of complex permission structures"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create complex old format
            old_content = [
                {
                    "path": "public/**",
                    "user": "*",
                    "permissions": ["read"]
                },
                {
                    "path": "shared/*.csv",
                    "user": "alice@example.com",
                    "permissions": ["read", "write"]
                },
                {
                    "path": "shared/*.csv",
                    "user": "bob@example.com",
                    "permissions": ["read"]
                },
                {
                    "path": "admin/*",
                    "user": "admin@example.com",
                    "permissions": ["admin"]
                },
                {
                    "path": "**",
                    "user": "owner@example.com",
                    "permissions": ["admin"]
                }
            ]
            
            test_dir = datasites / "complex"
            test_dir.mkdir(parents=True)
            old_file = test_dir / OLD_PERM_FILE
            new_file = test_dir / PERM_FILE
            
            with open(old_file, "w") as f:
                yaml.dump(old_content, f)
            
            # Enable auto-conversion
            set_auto_convert_permissions(True)
            
            # Load and convert
            perm = SyftPermission.from_file(new_file, datasites)
            
            # Verify conversion
            assert not old_file.exists()
            assert new_file.exists()
            
            with open(new_file, "r") as f:
                new_content = yaml.safe_load(f)
            
            # Should have 4 patterns (public/**, shared/*.csv, admin/*, **)
            patterns = [r["pattern"] for r in new_content["rules"]]
            assert "public/**" in patterns
            assert "shared/*.csv" in patterns
            assert "admin/*" in patterns
            assert "**" in patterns
            
            # Check shared/*.csv has both users
            shared_rule = next(r for r in new_content["rules"] if r["pattern"] == "shared/*.csv")
            assert "alice@example.com" in shared_rule["access"]["write"]
            # When we have write permission, read is implied, so alice should also be in write, not read
            assert "bob@example.com" in shared_rule["access"]["read"]
            assert "bob@example.com" not in shared_rule["access"].get("write", [])
    
    def test_get_computed_permission_auto_conversion(self):
        """Test that get_computed_permission triggers auto-conversion"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create directory structure with old permission files
            owner_dir = datasites / "owner@example.com"
            owner_dir.mkdir(parents=True)
            
            public_dir = owner_dir / "public"
            public_dir.mkdir(parents=True)
            
            # Create old format files
            owner_old = [
                {
                    "path": "**",
                    "user": "owner@example.com",
                    "permissions": ["admin"]
                }
            ]
            
            public_old = [
                {
                    "path": "**",
                    "user": "*",
                    "permissions": ["read"]
                }
            ]
            
            with open(owner_dir / OLD_PERM_FILE, "w") as f:
                yaml.dump(owner_old, f)
            
            with open(public_dir / OLD_PERM_FILE, "w") as f:
                yaml.dump(public_old, f)
            
            # Enable auto-conversion
            set_auto_convert_permissions(True)
            
            # Create client and get permissions (should trigger conversion)
            client = create_client("test@example.com", datasites.parent)
            perms = get_computed_permission(
                client=client,
                path=RelativePath("owner@example.com/public/file.txt")
            )
            
            # Check conversions happened
            assert not (owner_dir / OLD_PERM_FILE).exists()
            assert not (public_dir / OLD_PERM_FILE).exists()
            assert (owner_dir / PERM_FILE).exists()
            assert (public_dir / PERM_FILE).exists()
            
            # Check permissions are correct
            assert perms.has_permission(PermissionType.READ)
            assert not perms.has_permission(PermissionType.WRITE)
    
    def test_mixed_old_and_new_files(self):
        """Test handling of mixed old and new format files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            datasites = Path(tmpdir) / "datasites"
            datasites.mkdir(parents=True)
            
            # Create two directories
            old_dir = datasites / "old_style"
            old_dir.mkdir(parents=True)
            
            new_dir = datasites / "new_style"
            new_dir.mkdir(parents=True)
            
            # Old format in first directory
            old_content = [
                {
                    "path": "**",
                    "user": "*",
                    "permissions": ["read"]
                }
            ]
            
            with open(old_dir / OLD_PERM_FILE, "w") as f:
                yaml.dump(old_content, f)
            
            # New format in second directory
            new_content = {
                "terminal": True,
                "rules": [
                    {
                        "pattern": "**",
                        "access": {
                            "read": ["specific@example.com"]
                        }
                    }
                ]
            }
            
            with open(new_dir / PERM_FILE, "w") as f:
                yaml.dump(new_content, f)
            
            # Enable auto-conversion
            set_auto_convert_permissions(True)
            
            # Get permissions from both
            client = create_client("test@example.com", datasites.parent)
            
            # This should trigger conversion of old file
            old_perms = get_computed_permission(
                client=client,
                path=RelativePath("old_style/file.txt")
            )
            
            new_perms = get_computed_permission(
                client=client,
                path=RelativePath("new_style/file.txt")
            )
            
            # Check old was converted
            assert not (old_dir / OLD_PERM_FILE).exists()
            assert (old_dir / PERM_FILE).exists()
            
            # Check permissions
            assert old_perms.has_permission(PermissionType.READ)  # Public read
            assert not new_perms.has_permission(PermissionType.READ)  # Specific user only