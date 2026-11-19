-- ══════════════════════════════════════════════════════════════════
-- Script opcional: crea las tablas manualmente en phpMyAdmin
-- La app las crea automáticamente al arrancar.
-- Sincronizado con el dump real de cPanel (eddysbbq_asistencia.sql)
-- ══════════════════════════════════════════════════════════════════

-- Tabla de locales (sucursales)
CREATE TABLE IF NOT EXISTS locales (
    id     INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Locales por defecto (coinciden con los de producción en cPanel)
INSERT IGNORE INTO locales (id, nombre) VALUES
  (1, 'Vermont Plaza'),
  (2, 'Planta 1'),
  (3, 'Oficina'),
  (4, 'Village Plaza');

-- Tabla de cargos
CREATE TABLE IF NOT EXISTS cargos (
    id     INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Cargos por defecto (coinciden con los de producción en cPanel)
INSERT IGNORE INTO cargos (id, nombre) VALUES
  (1, 'Coordinador 1'),
  (2, 'Coordinador 2'),
  (3, 'Ayudante Cocina'),
  (4, 'Mesero'),
  (5, 'Cajero'),
  (6, 'Bartender'),
  (7, 'Coord. Cocina 1'),
  (9, 'Coord. Cocina 2'),
  (10, 'Sistemas'),
  (11, 'Limpieza'),
  (12, 'Auxiliar Contable'),
  (13, 'Recursos Humanos'),
  (14, 'Contabilidad'),
  (15, 'Asistente Administrativo');

-- Tabla de empleados (template NULL = sin huella)
CREATE TABLE IF NOT EXISTS employees (
    id         INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(255) NOT NULL,
    dept       VARCHAR(255) DEFAULT 'General',
    cargo      VARCHAR(255) DEFAULT '',
    is_admin   TINYINT(1) DEFAULT 0,
    admin_pin  VARCHAR(10) DEFAULT NULL,
    template   LONGBLOB DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Migración: si ya tienes la tabla employees sin columnas nuevas, ejecuta estos ALTER:
-- ALTER TABLE employees ADD COLUMN cargo VARCHAR(255) DEFAULT '' AFTER dept;
-- ALTER TABLE employees ADD COLUMN is_admin TINYINT(1) DEFAULT 0 AFTER cargo;
-- ALTER TABLE employees ADD COLUMN admin_pin VARCHAR(10) DEFAULT NULL AFTER is_admin;

-- Tabla de registros de asistencia
CREATE TABLE IF NOT EXISTS attendance (
    id            INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id   INT NOT NULL,
    employee_name VARCHAR(255) NOT NULL,
    dept          VARCHAR(255),
    local         VARCHAR(255) DEFAULT NULL,
    punch_type    VARCHAR(50) NOT NULL,
    timestamp     VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Migración: si ya tienes la tabla attendance sin la columna local:
-- ALTER TABLE attendance ADD COLUMN local VARCHAR(255) DEFAULT NULL AFTER dept;

-- Tabla de agentes
CREATE TABLE IF NOT EXISTS agents (
    id        VARCHAR(100) PRIMARY KEY,
    name      VARCHAR(255),
    api_key   VARCHAR(255) NOT NULL,
    last_seen VARCHAR(50),
    status    VARCHAR(50) DEFAULT 'offline'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabla de códigos de acceso
CREATE TABLE IF NOT EXISTS access_codes (
    id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(100) NOT NULL UNIQUE,
    descripcion VARCHAR(255) DEFAULT '',
    activo      TINYINT(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Códigos de acceso por defecto
INSERT IGNORE INTO access_codes (code, descripcion) VALUES
  ('eddys1234', 'sistemas'),
  ('Cg092528*', 'vermont coord 1');
